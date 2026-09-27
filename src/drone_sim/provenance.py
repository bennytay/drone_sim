"""Evidence, uncertainty, and lineage for canonical deployment facts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from drone_sim.ir import DeploymentIR, StrictModel


class ValueOrigin(StrEnum):
    """How a candidate value entered the evidence graph."""

    OBSERVED = "observed"
    MANUFACTURER_SPECIFIED = "manufacturer_specified"
    INFERRED = "inferred"
    ESTIMATED = "estimated"
    MODEL_DERIVED = "model_derived"
    ASSUMED = "assumed"


class ConfidenceLevel(StrEnum):
    """Ordinal confidence only; values are not calibrated probabilities."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class SourceLocationType(StrEnum):
    JSON_POINTER = "json_pointer"
    TEXT_LINES = "text_lines"
    PDF_PAGE = "pdf_page"
    TABLE_CELL = "table_cell"
    BYTE_RANGE = "byte_range"
    OTHER = "other"


class SourceAnchor(StrictModel):
    """An exact location in immutable source bytes."""

    source_path: str = Field(min_length=1)
    location_type: SourceLocationType
    locator: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExtractionMethod(StrictModel):
    """Versioned deterministic, manual, or model extraction method."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Uncertainty(StrictModel):
    """A qualitative assessment with its basis, not a fake probability."""

    confidence: ConfidenceLevel
    basis: str = Field(min_length=1)


class Assumption(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class EvidenceCandidate(StrictModel):
    """One possible value and the evidence chain supporting it."""

    id: str = Field(min_length=1)
    value: JsonValue
    origin: ValueOrigin
    sources: tuple[SourceAnchor, ...] = ()
    extraction: ExtractionMethod
    uncertainty: Uncertainty
    assumption_ids: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

    @model_validator(mode="after")
    def support_matches_origin(self) -> "EvidenceCandidate":
        if self.origin in {ValueOrigin.OBSERVED, ValueOrigin.MANUFACTURER_SPECIFIED}:
            if not self.sources:
                raise ValueError(f"{self.origin.value} values require a source anchor")
        elif self.origin == ValueOrigin.ASSUMED:
            if not self.assumption_ids:
                raise ValueError("assumed values require an explicit assumption")
        elif not (self.sources or self.derived_from or self.assumption_ids):
            raise ValueError(f"{self.origin.value} values require evidence or lineage")
        return self


class MaterialFact(StrictModel):
    """The chosen value for one Deployment IR leaf plus competing values."""

    path: str = Field(pattern=r"^/")
    selected: EvidenceCandidate
    competing: tuple[EvidenceCandidate, ...] = ()

    @model_validator(mode="after")
    def candidates_are_distinct(self) -> "MaterialFact":
        ids = [self.selected.id, *(candidate.id for candidate in self.competing)]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique within a material fact")
        return self


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def material_values(deployment: DeploymentIR) -> dict[str, JsonValue]:
    """Return every populated scalar IR leaf that can affect downstream work."""

    document = deployment.model_dump(mode="json", exclude_none=True)
    document.pop("schema_version", None)
    values: dict[str, JsonValue] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}/{_escape_pointer(str(key))}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")
        else:
            values[path] = value

    visit(document, "")
    return values


class EvidenceBackedDeployment(StrictModel):
    """A Deployment IR whose every populated material value is traceable."""

    evidence_version: Literal["0.1.0"] = "0.1.0"
    deployment: DeploymentIR
    facts: tuple[MaterialFact, ...]
    assumptions: tuple[Assumption, ...] = ()

    @model_validator(mode="after")
    def evidence_graph_is_complete(self) -> "EvidenceBackedDeployment":
        expected = material_values(self.deployment)
        by_path = {fact.path: fact for fact in self.facts}
        if len(by_path) != len(self.facts):
            raise ValueError("material fact paths must be unique")
        missing = sorted(set(expected) - set(by_path))
        extra = sorted(set(by_path) - set(expected))
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing evidence for: {', '.join(missing)}")
            if extra:
                details.append(f"evidence for unknown fields: {', '.join(extra)}")
            raise ValueError("; ".join(details))

        candidate_ids: set[str] = set()
        all_candidates: list[EvidenceCandidate] = []
        for path, expected_value in expected.items():
            fact = by_path[path]
            if fact.selected.value != expected_value:
                raise ValueError(f"selected evidence value does not match {path}")
            all_candidates.extend((fact.selected, *fact.competing))
        for candidate in all_candidates:
            if candidate.id in candidate_ids:
                raise ValueError(f"candidate ID is not unique: {candidate.id}")
            candidate_ids.add(candidate.id)

        assumption_ids = {assumption.id for assumption in self.assumptions}
        if len(assumption_ids) != len(self.assumptions):
            raise ValueError("assumption IDs must be unique")
        for candidate in all_candidates:
            unknown_assumptions = set(candidate.assumption_ids) - assumption_ids
            if unknown_assumptions:
                raise ValueError(
                    f"candidate {candidate.id} references unknown assumptions: "
                    f"{', '.join(sorted(unknown_assumptions))}"
                )
            unknown_inputs = set(candidate.derived_from) - candidate_ids
            if unknown_inputs:
                raise ValueError(
                    f"candidate {candidate.id} references unknown inputs: "
                    f"{', '.join(sorted(unknown_inputs))}"
                )
            if candidate.id in candidate.derived_from:
                raise ValueError(f"candidate {candidate.id} cannot derive from itself")

        graph = {
            candidate.id: candidate.derived_from for candidate in all_candidates
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(candidate_id: str) -> None:
            if candidate_id in visiting:
                raise ValueError("candidate derivation lineage contains a cycle")
            if candidate_id in visited:
                return
            visiting.add(candidate_id)
            for input_id in graph[candidate_id]:
                visit(input_id)
            visiting.remove(candidate_id)
            visited.add(candidate_id)

        for candidate_id in graph:
            visit(candidate_id)
        return self

    def fact(self, path: str) -> MaterialFact:
        """Look up a material fact by its stable JSON Pointer path."""

        for fact in self.facts:
            if fact.path == path:
                return fact
        raise KeyError(path)
