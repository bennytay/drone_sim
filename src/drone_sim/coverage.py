"""Deterministic applicability and coverage semantics for drone failure mechanisms."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.ir import DeploymentIR, StrictModel


class Comparison(StrEnum):
    EXISTS = "exists"
    EQUALS = "equals"
    IN = "in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class ApplicabilityStatus(StrEnum):
    APPLIES = "applies"
    RULED_OUT = "ruled_out"
    UNKNOWN = "unknown"


class CoverageState(StrEnum):
    UNEXAMINED = "unexamined"
    RULED_OUT = "ruled_out"
    TESTED = "tested"
    UNCERTAIN = "uncertain"
    ESCALATED = "escalated"


class Materiality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Testability(StrEnum):
    ANALYTICAL = "analytical"
    GEOMETRIC = "geometric"
    SIMULATION = "simulation"
    OBSERVATIONAL = "observational"
    HUMAN_REVIEW = "human_review"


class EvidencePredicate(StrictModel):
    """A deterministic predicate over canonical Deployment IR JSON pointers."""

    path: str = Field(pattern=r"^/")
    comparison: Comparison = Comparison.EXISTS
    value: float | str | bool | tuple[float | str | bool, ...] | None = None
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def value_matches_comparison(self) -> EvidencePredicate:
        if self.comparison == Comparison.EXISTS and self.value is not None:
            raise ValueError("exists predicates do not take a comparison value")
        if self.comparison != Comparison.EXISTS and self.value is None:
            raise ValueError("comparison predicates require a value")
        if self.comparison == Comparison.IN and not isinstance(self.value, tuple):
            raise ValueError("in predicates require a tuple value")
        return self


class ApplicabilityRule(StrictModel):
    """Evidence conditions that activate or rule out one mechanism."""

    all_of: tuple[EvidencePredicate, ...] = ()
    any_of: tuple[EvidencePredicate, ...] = ()
    ruled_out_by: tuple[EvidencePredicate, ...] = ()

    @model_validator(mode="after")
    def has_activation(self) -> ApplicabilityRule:
        if not self.all_of and not self.any_of:
            raise ValueError("applicability rules require all_of or any_of predicates")
        return self


class MechanismProfile(StrictModel):
    mechanism_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    prerequisites: tuple[str, ...] = Field(min_length=1)
    applicability: ApplicabilityRule
    materiality: Materiality
    testability: tuple[Testability, ...] = Field(min_length=1)


class EvidenceAssessment(StrictModel):
    predicate: EvidencePredicate
    result: bool | None
    observed_value: Any = None


class CoverageEntry(StrictModel):
    mechanism_id: str
    applicability: ApplicabilityStatus
    state: CoverageState
    materiality: Materiality
    testability: tuple[Testability, ...]
    prerequisites: tuple[str, ...]
    evidence: tuple[EvidenceAssessment, ...]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_state(self) -> CoverageEntry:
        if (
            self.applicability == ApplicabilityStatus.RULED_OUT
            and self.state != CoverageState.RULED_OUT
        ):
            raise ValueError("ruled-out mechanisms must have ruled_out coverage")
        if (
            self.applicability == ApplicabilityStatus.UNKNOWN
            and self.state != CoverageState.UNCERTAIN
        ):
            raise ValueError("unknown applicability must have uncertain coverage")
        if self.applicability == ApplicabilityStatus.APPLIES and self.state in {
            CoverageState.RULED_OUT,
            CoverageState.UNCERTAIN,
        }:
            raise ValueError(
                "applicable mechanisms start unexamined, tested, or escalated"
            )
        return self


class UnknownRisk(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    materiality: Materiality = Materiality.MEDIUM


class CoverageMap(StrictModel):
    taxonomy_version: str
    entries: tuple[CoverageEntry, ...]
    residual_unknowns: tuple[UnknownRisk, ...]

    @property
    def unexplored(self) -> tuple[CoverageEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.state
            in {
                CoverageState.UNEXAMINED,
                CoverageState.UNCERTAIN,
                CoverageState.ESCALATED,
            }
        )

    def record(
        self, mechanism_id: str, state: CoverageState, reason: str
    ) -> CoverageMap:
        """Return a new map after a deterministic test or escalation result."""
        updated: list[CoverageEntry] = []
        found = False
        for entry in self.entries:
            if entry.mechanism_id != mechanism_id:
                updated.append(entry)
                continue
            found = True
            if entry.applicability != ApplicabilityStatus.APPLIES:
                raise ValueError("only applicable mechanisms may receive test coverage")
            if state not in {
                CoverageState.TESTED,
                CoverageState.ESCALATED,
                CoverageState.UNCERTAIN,
            }:
                raise ValueError("test results must be tested, escalated, or uncertain")
            updated.append(entry.model_copy(update={"state": state, "reason": reason}))
        if not found:
            raise KeyError(mechanism_id)
        return self.model_copy(update={"entries": tuple(updated)})


def _resolve(document: Any, path: str) -> Any:
    value = document
    for token in path.removeprefix("/").split("/"):
        if not token:
            continue
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                return None
            value = value[token]
        elif isinstance(value, list):
            try:
                value = value[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value


def _assess(
    predicate: EvidencePredicate, document: dict[str, Any]
) -> EvidenceAssessment:
    observed = _resolve(document, predicate.path)
    if predicate.comparison == Comparison.EXISTS:
        return EvidenceAssessment(
            predicate=predicate,
            result=True if observed not in (None, (), [], {}) else None,
            observed_value=observed,
        )
    if observed is None:
        return EvidenceAssessment(predicate=predicate, result=None)
    try:
        if predicate.comparison == Comparison.EQUALS:
            result = observed == predicate.value
        elif predicate.comparison == Comparison.IN:
            result = observed in predicate.value
        elif predicate.comparison == Comparison.GT:
            result = observed > predicate.value
        elif predicate.comparison == Comparison.GTE:
            result = observed >= predicate.value
        elif predicate.comparison == Comparison.LT:
            result = observed < predicate.value
        elif predicate.comparison == Comparison.LTE:
            result = observed <= predicate.value
        else:  # pragma: no cover - exhaustive over the closed Comparison enum.
            raise ValueError(f"unsupported comparison: {predicate.comparison}")
    except TypeError:
        result = False
    return EvidenceAssessment(
        predicate=predicate, result=result, observed_value=observed
    )


def _status(
    rule: ApplicabilityRule, document: dict[str, Any]
) -> tuple[ApplicabilityStatus, tuple[EvidenceAssessment, ...], str]:
    assessments = tuple(
        _assess(predicate, document)
        for predicate in (*rule.all_of, *rule.any_of, *rule.ruled_out_by)
    )
    cut = len(rule.all_of) + len(rule.any_of)
    activation, exclusions = assessments[:cut], assessments[cut:]
    if any(item.result is True for item in exclusions):
        return (
            ApplicabilityStatus.RULED_OUT,
            assessments,
            "Deactivation evidence rules this mechanism out.",
        )
    all_results = [item.result for item in activation[: len(rule.all_of)]]
    any_results = [item.result for item in activation[len(rule.all_of) :]]
    if False in all_results:
        return (
            ApplicabilityStatus.RULED_OUT,
            assessments,
            "Required activation evidence is absent or contradicts this mechanism.",
        )
    if rule.any_of and True not in any_results:
        if None in any_results or None in all_results:
            return (
                ApplicabilityStatus.UNKNOWN,
                assessments,
                "Activation evidence is incomplete.",
            )
        return (
            ApplicabilityStatus.RULED_OUT,
            assessments,
            "No alternative activation condition is present.",
        )
    if None in all_results or None in any_results:
        return (
            ApplicabilityStatus.UNKNOWN,
            assessments,
            "Activation evidence is incomplete.",
        )
    return (
        ApplicabilityStatus.APPLIES,
        assessments,
        "All deterministic activation conditions are satisfied.",
    )


def default_profiles(
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
) -> tuple[MechanismProfile, ...]:
    """Conservative baseline profiles; specialized rules are added as evidence matures."""
    profiles = []
    for leaf in taxonomy.leaves():
        profiles.append(
            MechanismProfile(
                mechanism_id=leaf.id,
                prerequisites=leaf.context_paths,
                applicability=ApplicabilityRule(
                    all_of=tuple(
                        EvidencePredicate(
                            path=path, description=f"Required context: {path}"
                        )
                        for path in leaf.context_paths
                    )
                ),
                materiality=Materiality.HIGH
                if any(
                    term in leaf.id
                    for term in (
                        "collision",
                        "energy",
                        "aircraft",
                        "airspace",
                        "containment",
                    )
                )
                else Materiality.MEDIUM,
                testability=(Testability.GEOMETRIC,)
                if "geometry" in leaf.id
                else (Testability.ANALYTICAL, Testability.SIMULATION),
            )
        )
    return tuple(profiles)


def assess_coverage(
    deployment: DeploymentIR,
    profiles: tuple[MechanismProfile, ...] | None = None,
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
) -> CoverageMap:
    """Build an auditable initial map; it never treats missing evidence as irrelevant."""
    profiles = profiles or default_profiles(taxonomy)
    by_id = {profile.mechanism_id: profile for profile in profiles}
    expected = {leaf.id for leaf in taxonomy.leaves()}
    if set(by_id) != expected:
        raise ValueError("profiles must cover every taxonomy mechanism exactly once")
    document = deployment.model_dump(mode="json")
    entries = []
    for mechanism_id in sorted(by_id):
        profile = by_id[mechanism_id]
        applicability, evidence, reason = _status(profile.applicability, document)
        state = {
            ApplicabilityStatus.APPLIES: CoverageState.UNEXAMINED,
            ApplicabilityStatus.RULED_OUT: CoverageState.RULED_OUT,
            ApplicabilityStatus.UNKNOWN: CoverageState.UNCERTAIN,
        }[applicability]
        entries.append(
            CoverageEntry(
                mechanism_id=mechanism_id,
                applicability=applicability,
                state=state,
                materiality=profile.materiality,
                testability=profile.testability,
                prerequisites=profile.prerequisites,
                evidence=evidence,
                reason=reason,
            )
        )
    return CoverageMap(
        taxonomy_version=taxonomy.version,
        entries=tuple(entries),
        residual_unknowns=(
            UnknownRisk(
                id="taxonomy_gap",
                description="Failure mechanisms not represented in the current taxonomy.",
                reason="Coverage of known mechanisms is not a proof that no deployment-specific risk remains.",
            ),
        ),
    )
