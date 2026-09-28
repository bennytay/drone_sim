"""Replayable LLM evidence-search loop over bounded deterministic tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import ConfigDict, Field, ValidationError, model_validator

from drone_sim.adapters import ParsedSource
from drone_sim.agent_tools import AgentToolRuntime
from drone_sim.context import (
    DEFAULTS,
    REQUIRED_FIELDS,
    CandidateFact,
    ContextOrchestrator,
    DeploymentState,
    InspectionEvent,
)
from drone_sim.document_extraction import extract_document_candidates
from drone_sim.ir import DeploymentIR, StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)
from drone_sim.provenance import EvidenceBackedDeployment
from drone_sim.reconstruction import DEPENDENCY_BY_FIELD, link_entities
from drone_sim.schema_mapping import FieldMapping, apply_mappings
from drone_sim.validation import ReadinessReport


class ContextActionKind(StrEnum):
    SEARCH = "search"
    STOP = "stop"
    ASK = "ask"


class ContextAction(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ContextActionKind
    field: str | None = None
    query: str | None = None
    limit: int = Field(default=3, ge=1, le=20)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_search(self) -> "ContextAction":
        if self.kind == ContextActionKind.SEARCH:
            if self.field not in DEPENDENCY_BY_FIELD or not self.query:
                raise ValueError("search requires a canonical field and query")
        elif self.field is not None or self.query is not None:
            raise ValueError("ask/stop actions cannot select a field or query")
        return self


class ContextStopReason(StrEnum):
    READY = "ready"
    BUDGET = "budget_exhausted"
    NO_EVIDENCE = "no_promising_evidence"
    OPERATOR = "operator_required"
    MODEL_STOP = "model_stop"


class ContextAgentResult(StrictModel):
    evidence: EvidenceBackedDeployment | None
    state: DeploymentState
    readiness: ReadinessReport
    stop_reason: ContextStopReason
    decisions_used: int = Field(ge=0)


class SupplementalExtractor(Protocol):
    """Optional verified extractor for content deterministic aliases cannot map."""

    def extract(
        self, *, field: str, source_path: str, parsed: ParsedSource
    ) -> tuple[CandidateFact, ...]: ...


class SchemaMappingResponse(StrictModel):
    mappings: tuple[FieldMapping, ...] = Field(min_length=1)


class LLMSchemaExtractor:
    """Apply BEN-70's deterministic mapping to an LLM-proposed schema map."""

    def __init__(self, runner: StructuredOutputRunner, *, model: str):
        self.runner = runner
        self.model = model

    def extract(
        self, *, field: str, source_path: str, parsed: ParsedSource
    ) -> tuple[CandidateFact, ...]:
        if not isinstance(parsed.content, dict):
            return ()
        prompt = Prompt(
            id="context-schema-mapping",
            version="1",
            messages=(
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Map explicit fields in this unfamiliar drone export to canonical "
                        "Deployment IR paths. Never supply values; return path mappings only."
                    ),
                ),
                LLMMessage(
                    role=MessageRole.USER,
                    content=json.dumps(
                        {
                            "requested_field": field,
                            "source_path": source_path,
                            "document": parsed.content,
                        },
                        sort_keys=True,
                    ),
                ),
            ),
        )
        response, _ = self.runner.run(
            task=LLMTask.EXTRACTION,
            model=self.model,
            prompt=prompt,
            contract=SchemaMappingResponse,
        )
        relevant = tuple(
            mapping
            for mapping in response.mappings
            if mapping.canonical_path == f"/{field}"
            or mapping.canonical_path.startswith(f"/{field}/")
        )
        if not relevant:
            return ()
        values, anchors = apply_mappings(parsed.content, relevant)
        if field not in values:
            return ()
        source_locations = {
            canonical.removeprefix(f"/{field}") or "": source_pointer
            for canonical, source_pointer in anchors.items()
        }
        return (
            CandidateFact(
                field=field,
                value=values[field],
                source_path=source_path,
                adapter="llm_schema_mapping",
                source_location=next(iter(source_locations.values())),
                source_locations=source_locations,
                source_sha256=parsed.sha256,
                origin="inferred",
                confidence="medium",
                uncertainty_basis="LLM-proposed paths with deterministic value copying",
            ),
        )


class CompositeSupplementalExtractor:
    def __init__(self, *extractors: SupplementalExtractor):
        self.extractors = extractors

    def extract(
        self, *, field: str, source_path: str, parsed: ParsedSource
    ) -> tuple[CandidateFact, ...]:
        return tuple(
            candidate
            for extractor in self.extractors
            for candidate in extractor.extract(
                field=field, source_path=source_path, parsed=parsed
            )
        )


class LLMDocumentExtractor:
    """Use BEN-69's quote-verifying document extraction inside the loop."""

    def __init__(
        self,
        root: Path,
        runner: StructuredOutputRunner,
        *,
        model: str,
        max_source_bytes: int = 10 * 1024 * 1024,
    ):
        self.root = root.resolve(strict=True)
        self.runner = runner
        self.model = model
        self.max_source_bytes = max_source_bytes

    def extract(
        self, *, field: str, source_path: str, parsed: ParsedSource
    ) -> tuple[CandidateFact, ...]:
        if parsed.adapter not in {"text", "pdf", "docx"}:
            return ()
        prompt = Prompt(
            id="context-document-extraction",
            version="1",
            messages=(
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Propose only explicitly quoted drone deployment facts for the "
                        "requested canonical field. Return JSON matching the contract."
                    ),
                ),
                LLMMessage(
                    role=MessageRole.USER,
                    content=json.dumps(
                        {
                            "field": field,
                            "source_path": source_path,
                            "bounded_parse": parsed.content,
                        },
                        sort_keys=True,
                    ),
                ),
            ),
        )
        source = (self.root / source_path).resolve(strict=True)
        if not source.is_relative_to(self.root):
            raise ValueError("document path escapes deployment root")
        if source.stat().st_size > self.max_source_bytes:
            raise ValueError("document exceeds extraction source limit")
        return extract_document_candidates(
            runner=self.runner,
            model=self.model,
            prompt=prompt,
            field=field,
            source_bytes=source.read_bytes(),
            parsed=parsed,
        )


class ContextPolicy:
    """Deterministic fallback policy retained for no-LLM operation and tests."""

    def choose(
        self, unresolved: tuple[str, ...], *, calls_used: int, max_calls: int
    ) -> ContextAction:
        if not unresolved:
            return ContextAction(
                kind=ContextActionKind.STOP,
                rationale=ContextStopReason.READY.value,
            )
        if calls_used >= max_calls:
            return ContextAction(
                kind=ContextActionKind.STOP,
                rationale=ContextStopReason.BUDGET.value,
            )
        field = unresolved[0].split("/")[1]
        return ContextAction(
            kind=ContextActionKind.SEARCH,
            field=field,
            query=DEPENDENCY_BY_FIELD[field].query,
            rationale="Highest-priority unresolved deployment field",
        )


def record_action(state: DeploymentState, action: ContextAction) -> None:
    """Persist a model/policy decision beside deterministic inspections."""

    state.trace.append(
        InspectionEvent(
            timestamp=datetime.now(UTC),
            field=action.field or "agent",
            query=action.query or action.kind.value,
            source_path=None,
            reason=action.rationale,
            outcome=(
                "no_candidate"
                if action.kind == ContextActionKind.SEARCH
                else "unresolved"
            ),
        )
    )


class ContextAgentLoop:
    """Plan, inspect, extract, reassess, and stop with persisted rationale."""

    def __init__(
        self,
        root: Path,
        state_path: Path,
        *,
        runner: StructuredOutputRunner,
        model: str,
        max_decisions: int = 12,
        files_per_decision: int = 3,
        tool_ledger_path: Path | None = None,
        supplemental_extractor: SupplementalExtractor | None = None,
    ) -> None:
        if max_decisions < 1 or not 1 <= files_per_decision <= 20:
            raise ValueError("agent budgets must be positive and bounded")
        self.orchestrator = ContextOrchestrator(root, state_path)
        self.runner = runner
        self.model = model
        self.max_decisions = max_decisions
        self.files_per_decision = files_per_decision
        self.tool_ledger_path = tool_ledger_path
        self.supplemental_extractor = supplemental_extractor

    def run(self) -> ContextAgentResult:
        state = self.orchestrator.store.load_or_create(self.orchestrator.index.root)
        previous_signatures = dict(state.index_signatures)
        self.orchestrator._refresh_index_state(state)
        index_changed = bool(previous_signatures) and (
            previous_signatures != state.index_signatures
        )
        readiness = self.orchestrator.assess(state)
        persisted_stop = self._persisted_stop_reason(state)
        if persisted_stop is not None and not index_changed:
            return ContextAgentResult(
                evidence=self._evidence(state),
                state=state,
                readiness=readiness,
                stop_reason=persisted_stop,
                decisions_used=0,
            )
        runtime = AgentToolRuntime(
            self.orchestrator.index.root,
            state,
            ledger_path=self.tool_ledger_path,
            state_path=self.orchestrator.store.path,
        )
        index = runtime.list_index()
        decisions = 0

        while True:
            readiness = self.orchestrator.assess(state)
            unresolved = runtime.list_unresolved(readiness.unresolved_paths)
            if readiness.ready:
                return self._finish(
                    state, readiness, ContextStopReason.READY, decisions
                )
            if decisions >= self.max_decisions:
                return self._finish(
                    state, readiness, ContextStopReason.BUDGET, decisions
                )

            action, _ = self.runner.run(
                task=LLMTask.EXTRACTION,
                model=self.model,
                prompt=self._prompt(readiness, unresolved, index, state),
                contract=ContextAction,
            )
            decisions += 1
            record_action(state, action)
            self.orchestrator.store.save(state)

            if action.kind == ContextActionKind.ASK:
                return self._finish(
                    state, readiness, ContextStopReason.OPERATOR, decisions
                )
            if action.kind == ContextActionKind.STOP:
                return self._finish(
                    state, readiness, ContextStopReason.MODEL_STOP, decisions
                )
            assert action.field is not None and action.query is not None
            candidates = runtime.search_files(
                action.query, min(action.limit, self.files_per_decision)
            )
            promising = tuple(path for path in candidates if path not in state.inspected_paths)
            if not promising:
                return self._finish(
                    state, readiness, ContextStopReason.NO_EVIDENCE, decisions
                )
            for source_path in promising:
                parsed = ParsedSource.model_validate(runtime.parse_file(source_path))
                self._ingest(action.field, source_path, parsed, state, action.rationale)
            state.attempted_fields.add(action.field)
            state.entity_links = list(link_entities(state.parsed_sources))
            self.orchestrator.store.save(state)

    def _ingest(
        self,
        field: str,
        source_path: str,
        parsed: ParsedSource,
        state: DeploymentState,
        rationale: str,
    ) -> None:
        record = next(item for item in self.orchestrator.index.records if item.path == source_path)
        state.parsed_sources[source_path] = parsed
        state.inspected_paths.add(source_path)
        extracted = self.orchestrator._extract(field, source_path, parsed)
        if extracted is not None:
            self.orchestrator._record_candidates(record, parsed, field, extracted, state)
        elif self.supplemental_extractor:
            for candidate in self.supplemental_extractor.extract(
                field=field, source_path=source_path, parsed=parsed
            ):
                if candidate.field != field or candidate.source_path != source_path:
                    raise ValueError("supplemental extractor returned an unrelated candidate")
                state.candidates.setdefault(field, []).append(candidate)
        state.trace.append(
            InspectionEvent(
                timestamp=datetime.now(UTC),
                field=field,
                query="extract",
                source_path=source_path,
                reason=rationale,
                adapter=parsed.adapter,
                outcome=(
                    "candidate_extracted"
                    if field in state.candidates
                    else "no_candidate"
                ),
            )
        )

    def _finish(
        self,
        state: DeploymentState,
        readiness: ReadinessReport,
        reason: ContextStopReason,
        decisions: int,
    ) -> ContextAgentResult:
        record_action(
            state,
            ContextAction(kind=ContextActionKind.STOP, rationale=reason.value),
        )
        state.entity_links = list(link_entities(state.parsed_sources))
        self.orchestrator.store.save(state)
        evidence = self._evidence(state)
        return ContextAgentResult(
            evidence=evidence,
            state=state,
            readiness=readiness,
            stop_reason=reason,
            decisions_used=decisions,
        )

    def _evidence(self, state: DeploymentState) -> EvidenceBackedDeployment | None:
        if not REQUIRED_FIELDS.issubset(state.candidates):
            return None
        values = dict(DEFAULTS)
        values.update({field: facts[0].value for field, facts in state.candidates.items()})
        try:
            deployment = DeploymentIR.model_validate(values)
        except ValidationError:
            return None
        return self.orchestrator._evidence_backed(deployment, state)

    @staticmethod
    def _persisted_stop_reason(state: DeploymentState) -> ContextStopReason | None:
        if not state.trace or state.trace[-1].query != ContextActionKind.STOP:
            return None
        try:
            return ContextStopReason(state.trace[-1].reason)
        except ValueError:
            return None

    @staticmethod
    def _prompt(
        readiness: ReadinessReport,
        unresolved: tuple[str, ...],
        index: tuple[dict[str, object], ...],
        state: DeploymentState,
    ) -> Prompt:
        return Prompt(
            id="agentic-context-search",
            version="1",
            messages=(
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Plan one bounded evidence-search action for a drone deployment. "
                        "Do not decide readiness; deterministic validation owns that decision."
                    ),
                ),
                LLMMessage(
                    role=MessageRole.USER,
                    content=json.dumps(
                        {
                            "readiness": readiness.model_dump(mode="json"),
                            "unresolved": unresolved,
                            "inspected_paths": sorted(state.inspected_paths),
                            "file_index": index,
                        },
                        sort_keys=True,
                    ),
                ),
            ),
        )
