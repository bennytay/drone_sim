"""Read-only, dependency-driven reconstruction of Deployment IR from a folder."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.ir import DeploymentIR
from drone_sim.provenance import (
    ConfidenceLevel,
    EvidenceBackedDeployment,
    EvidenceCandidate,
    ExtractionMethod,
    MaterialFact,
    SourceAnchor,
    SourceLocationType,
    Uncertainty,
    ValueOrigin,
    material_values,
)


TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_FILE_BYTES = 10 * 1024 * 1024


def _tokens(value: str) -> set[str]:
    return set(TOKEN_RE.findall(value.lower()))


class FileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size_bytes: int = Field(ge=0)
    media_type: str | None = None


class SemanticRanker(Protocol):
    """Optional embedding/search service; it never receives file contents."""

    def rank(self, query: str, records: Sequence[FileRecord]) -> Sequence[str]: ...


class DirectoryIndex:
    """Metadata-only index of regular, non-symlink files below one root."""

    def __init__(self, root: Path, records: Sequence[FileRecord]) -> None:
        self.root = root.resolve(strict=True)
        self.records = tuple(records)

    @classmethod
    def build(cls, root: Path) -> "DirectoryIndex":
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"deployment root is not a directory: {resolved}")

        records: list[FileRecord] = []
        for current, dirnames, filenames in os.walk(resolved, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames if not (current_path / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current_path / name
                if path.is_symlink() or not path.is_file():
                    continue
                records.append(
                    FileRecord(
                        path=path.relative_to(resolved).as_posix(),
                        size_bytes=path.stat().st_size,
                        media_type=mimetypes.guess_type(path.name)[0],
                    )
                )
        return cls(resolved, records)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        semantic_ranker: SemanticRanker | None = None,
    ) -> tuple[FileRecord, ...]:
        query_tokens = _tokens(query)
        lexical: dict[str, float] = {}
        for record in self.records:
            path_tokens = _tokens(record.path)
            overlap = query_tokens & path_tokens
            if overlap:
                lexical[record.path] = float(len(overlap)) + (
                    len(overlap) / max(len(path_tokens), 1)
                )

        semantic: dict[str, float] = {}
        if semantic_ranker:
            ranked_paths = semantic_ranker.rank(query, self.records)
            semantic = {
                path: 1.0 / (rank + 1) for rank, path in enumerate(ranked_paths)
            }

        scored = [
            (lexical.get(record.path, 0) + semantic.get(record.path, 0), record)
            for record in self.records
        ]
        scored.sort(key=lambda item: (-item[0], item[1].path))
        return tuple(record for score, record in scored if score > 0)[:limit]


class ParsedFile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    adapter: str
    content: Any
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeterministicFileReader:
    """Bounded parsers with path confinement and no write capability."""

    def __init__(self, root: Path, *, max_file_bytes: int = MAX_FILE_BYTES) -> None:
        self.root = root.resolve(strict=True)
        self.max_file_bytes = max_file_bytes

    def parse(self, relative_path: str) -> ParsedFile:
        unresolved = self.root / relative_path
        if unresolved.is_symlink():
            raise ValueError("symlinks are not readable deployment evidence")
        path = unresolved.resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError("file path escapes the deployment root")
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError(f"file exceeds {self.max_file_bytes} byte read limit")

        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        suffix = path.suffix.lower()
        if suffix in {".json", ".geojson"}:
            return ParsedFile(
                adapter="json", content=json.loads(raw.decode("utf-8")), sha256=digest
            )
        if suffix == ".csv":
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
            return ParsedFile(adapter="csv", content=rows, sha256=digest)
        if suffix in {".md", ".txt"}:
            return ParsedFile(adapter="text", content=raw.decode("utf-8"), sha256=digest)
        raise ValueError(f"no deterministic adapter for {suffix or 'extensionless file'}")


class CandidateFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any
    source_path: str
    adapter: str
    source_location: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: ValueOrigin = ValueOrigin.OBSERVED
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    uncertainty_basis: str = "Source supplied no calibrated confidence information"


LiteralOutcome = Literal["candidate_extracted", "no_candidate", "unresolved", "parse_error"]


class InspectionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    field: str
    query: str
    source_path: str | None
    reason: str
    adapter: str | None = None
    outcome: LiteralOutcome


class DeploymentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_version: str = "0.2.0"
    root: str
    candidates: dict[str, list[CandidateFact]] = Field(default_factory=dict)
    attempted_fields: set[str] = Field(default_factory=set)
    inspected_paths: set[str] = Field(default_factory=set)
    trace: list[InspectionEvent] = Field(default_factory=list)


class StateStore:
    """Atomic state persistence outside the read-only deployment folder."""

    def __init__(self, path: Path, deployment_root: Path) -> None:
        self.path = path.resolve()
        root = deployment_root.resolve(strict=True)
        if self.path.is_relative_to(root):
            raise ValueError("state path must be outside the read-only deployment root")

    def load_or_create(self, root: Path) -> DeploymentState:
        if not self.path.exists():
            return DeploymentState(root=str(root.resolve(strict=True)))
        state = DeploymentState.model_validate_json(self.path.read_text())
        if Path(state.root) != root.resolve(strict=True):
            raise ValueError("persisted state belongs to a different deployment root")
        return state

    def save(self, state: DeploymentState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


FIELD_QUERIES: dict[str, str] = {
    "deployment_id": "deployment identifier manifest overview",
    "vehicle": "vehicle aircraft drone uav airframe specification",
    "payloads": "payload sensor camera cargo specification",
    "mission": "mission route waypoints flight plan objective",
    "site": "site environment location map mesh geometry",
    "conditions": "conditions weather wind visibility temperature",
    "autonomy": "autonomy controller flight control configuration",
    "constraints": "constraints limits geofence airspace operations weather",
    "success_criteria": "success criteria pass threshold metrics",
    "telemetry": "telemetry flight log historical data",
    "raw_data": "raw data imagery observations",
    "models": "models dynamics geometry sensor environment",
}

REQUIRED_FIELDS = {
    "deployment_id",
    "vehicle",
    "mission",
    "site",
    "autonomy",
    "success_criteria",
}

DEFAULTS: dict[str, Any] = {
    "schema_version": "0.1.0",
    "payloads": [],
    "conditions": None,
    "constraints": [],
    "telemetry": [],
    "raw_data": [],
    "models": [],
}


class ContextOrchestrator:
    """Resolve missing IR fields by searching before reading any file."""

    def __init__(
        self,
        root: Path,
        state_path: Path,
        *,
        semantic_ranker: SemanticRanker | None = None,
        candidates_per_field: int = 3,
    ) -> None:
        self.index = DirectoryIndex.build(root)
        self.reader = DeterministicFileReader(self.index.root)
        self.store = StateStore(state_path, self.index.root)
        self.semantic_ranker = semantic_ranker
        self.candidates_per_field = candidates_per_field

    def run(self) -> tuple[EvidenceBackedDeployment | None, DeploymentState]:
        state = self.store.load_or_create(self.index.root)
        for field, query in FIELD_QUERIES.items():
            if field in state.candidates or field in state.attempted_fields:
                continue
            self._resolve(field, query, state)
            self.store.save(state)

        if not REQUIRED_FIELDS.issubset(state.candidates):
            return None, state

        values = dict(DEFAULTS)
        values.update({key: facts[0].value for key, facts in state.candidates.items()})
        deployment = DeploymentIR.model_validate(values)
        return self._evidence_backed(deployment, state), state

    def _resolve(self, field: str, query: str, state: DeploymentState) -> None:
        matches = self.index.search(
            query,
            limit=self.candidates_per_field,
            semantic_ranker=self.semantic_ranker,
        )
        unread = [record for record in matches if record.path not in state.inspected_paths]
        if not unread:
            state.attempted_fields.add(field)
            state.trace.append(
                InspectionEvent(
                    timestamp=datetime.now(UTC),
                    field=field,
                    query=query,
                    source_path=None,
                    reason="No uninspected relevant file was found",
                    outcome="unresolved",
                )
            )
            return

        for record in unread:
            state.inspected_paths.add(record.path)
            try:
                parsed = self.reader.parse(record.path)
                extracted = self._extract(field, record.path, parsed.content)
                outcome = "candidate_extracted" if extracted is not None else "no_candidate"
                state.trace.append(
                    InspectionEvent(
                        timestamp=datetime.now(UTC),
                        field=field,
                        query=query,
                        source_path=record.path,
                        reason=f"Path ranked for unresolved field '{field}'",
                        adapter=parsed.adapter,
                        outcome=outcome,
                    )
                )
                if extracted is not None:
                    self._record_candidates(record.path, parsed, field, extracted, state)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                state.trace.append(
                    InspectionEvent(
                        timestamp=datetime.now(UTC),
                        field=field,
                        query=query,
                        source_path=record.path,
                        reason=str(error),
                        outcome="parse_error",
                    )
                )
        state.attempted_fields.add(field)

    @staticmethod
    def _record_candidates(
        source_path: str,
        parsed: ParsedFile,
        requested_field: str,
        extracted: tuple[Any, str],
        state: DeploymentState,
    ) -> None:
        extracted_value, extracted_location = extracted
        values = {requested_field: (extracted_value, extracted_location)}
        if isinstance(parsed.content, dict):
            values.update(
                (field, (parsed.content[field], f"/{_escape_pointer(field)}"))
                for field in FIELD_QUERIES
                if field in parsed.content
            )
        for field, (value, source_location) in values.items():
            candidates = state.candidates.setdefault(field, [])
            if any(
                candidate.source_path == source_path
                and candidate.source_location == source_location
                for candidate in candidates
            ):
                continue
            candidates.append(
                CandidateFact(
                    field=field,
                    value=value,
                    source_path=source_path,
                    adapter=parsed.adapter,
                    source_location=source_location,
                    source_sha256=parsed.sha256,
                ),
            )

    @staticmethod
    def _extract(
        field: str, source_path: str, content: Any
    ) -> tuple[Any, str] | None:
        if not isinstance(content, dict):
            return None
        if field in content:
            return content[field], f"/{_escape_pointer(field)}"
        stem = Path(source_path).stem
        if _tokens(stem) == _tokens(field):
            return content, ""
        return None

    @staticmethod
    def _evidence_backed(
        deployment: DeploymentIR, state: DeploymentState
    ) -> EvidenceBackedDeployment:
        selected_values = material_values(deployment)
        facts: list[MaterialFact] = []
        for path, value in selected_values.items():
            top_level, relative = _split_deployment_path(path)
            candidates = state.candidates[top_level]
            selected = _leaf_candidate(candidates[0], path, relative, value)
            competing: list[EvidenceCandidate] = []
            for candidate in candidates[1:]:
                alternative = _value_at_pointer(candidate.value, relative)
                if alternative is _MISSING or alternative == value:
                    continue
                competing.append(_leaf_candidate(candidate, path, relative, alternative))
            facts.append(
                MaterialFact(path=path, selected=selected, competing=tuple(competing))
            )
        return EvidenceBackedDeployment(deployment=deployment, facts=tuple(facts))


_MISSING = object()


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _unescape_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _split_deployment_path(path: str) -> tuple[str, str]:
    parts = path.removeprefix("/").split("/")
    relative = "/" + "/".join(parts[1:]) if len(parts) > 1 else ""
    return _unescape_pointer(parts[0]), relative


def _value_at_pointer(value: Any, pointer: str) -> Any:
    current = value
    for encoded in pointer.removeprefix("/").split("/"):
        if not encoded:
            continue
        token = _unescape_pointer(encoded)
        try:
            current = current[int(token)] if isinstance(current, list) else current[token]
        except (IndexError, KeyError, TypeError, ValueError):
            return _MISSING
    return current


def _leaf_candidate(
    candidate: CandidateFact, deployment_path: str, relative_path: str, value: Any
) -> EvidenceCandidate:
    source_location = candidate.source_location + relative_path
    identity = "\0".join(
        (candidate.source_sha256, source_location, deployment_path, repr(value))
    )
    candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return EvidenceCandidate(
        id=candidate_id,
        value=value,
        origin=candidate.origin,
        sources=(
            SourceAnchor(
                source_path=candidate.source_path,
                location_type=SourceLocationType.JSON_POINTER,
                locator=source_location,
                sha256=candidate.source_sha256,
            ),
        ),
        extraction=ExtractionMethod(name=candidate.adapter, version="1"),
        uncertainty=Uncertainty(
            confidence=candidate.confidence, basis=candidate.uncertainty_basis
        ),
    )
