"""Operator-confirmed conflict resolution and clarification workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ConfigDict, Field, JsonValue

from drone_sim.context import CandidateFact, ContextOrchestrator, DeploymentState
from drone_sim.ir import StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)
from drone_sim.provenance import (
    ConfidenceLevel,
    ConflictResolution,
    EvidenceBackedDeployment,
    MaterialFact,
    ResolutionMethod,
    ValueOrigin,
)
from drone_sim.reconstruction import ClarificationRequest
from drone_sim.validation import ReadinessReport


class ResolutionProposal(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: ResolutionMethod
    selected_candidate_id: str = Field(min_length=1)
    rejected_candidate_ids: tuple[str, ...] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confirmation_question: str = Field(min_length=1)


class ClarificationProposal(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1)
    value: JsonValue
    question: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class OperatorAnswers(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_id: str = Field(min_length=1)
    conflict_confirmations: dict[str, bool] = Field(default_factory=dict)
    clarification_answers: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> "OperatorAnswers":
        return cls.model_validate_json(path.read_text())


class OperatorInteraction(StrictModel):
    kind: str
    path_or_field: str
    question: str
    explanation: str
    confirmed: bool


class OperatorSessionResult(StrictModel):
    evidence: EvidenceBackedDeployment | None
    state: DeploymentState
    readiness: ReadinessReport
    interactions: tuple[OperatorInteraction, ...]


def confirm_resolution(
    proposal: ResolutionProposal, *, operator_confirmed: bool
) -> ConflictResolution:
    if not operator_confirmed:
        raise PermissionError(
            "conflict resolution requires explicit operator confirmation"
        )
    if proposal.method != ResolutionMethod.OPERATOR_DECISION:
        raise ValueError("confirmed model proposals must use operator_decision")
    return ConflictResolution(
        method=ResolutionMethod.OPERATOR_DECISION,
        selected_candidate_id=proposal.selected_candidate_id,
        rejected_candidate_ids=proposal.rejected_candidate_ids,
        rationale=proposal.rationale,
    )


def operator_answer_candidate(
    *, field: str, value: object, operator_id: str, rationale: str
) -> CandidateFact:
    """Turn a scripted or interactive operator answer into observed evidence."""

    source = f"operator:{operator_id}"
    identity = json.dumps(
        {
            "field": field,
            "value": value,
            "operator_id": operator_id,
            "rationale": rationale,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CandidateFact(
        field=field,
        value=value,
        source_path=source,
        adapter="operator_confirmation",
        source_location="answer",
        source_sha256=hashlib.sha256(identity.encode()).hexdigest(),
        origin=ValueOrigin.OBSERVED,
        confidence=ConfidenceLevel.HIGH,
        uncertainty_basis=rationale,
    )


class OperatorResolutionSession:
    """Resolve a persisted context state using replayed or interactive answers."""

    def __init__(
        self,
        root: Path,
        state_path: Path,
        *,
        runner: StructuredOutputRunner,
        model: str,
        answers_path: Path,
    ) -> None:
        self.orchestrator = ContextOrchestrator(root, state_path)
        self.runner = runner
        self.model = model
        self.answers = OperatorAnswers.from_file(answers_path)

    def run(self) -> OperatorSessionResult:
        evidence, state = self.orchestrator.run()
        interactions: list[OperatorInteraction] = []
        if evidence is not None:
            for fact in evidence.facts:
                if not fact.competing or fact.path in state.resolutions:
                    continue
                proposal = self._propose_resolution(fact)
                expected_rejected = {item.id for item in fact.competing}
                if (
                    proposal.selected_candidate_id != fact.selected.id
                    or set(proposal.rejected_candidate_ids) != expected_rejected
                ):
                    raise ValueError(
                        "resolution proposal must account for the selected candidate and every competitor"
                    )
                confirmed = self.answers.conflict_confirmations.get(fact.path, False)
                interactions.append(
                    OperatorInteraction(
                        kind="conflict",
                        path_or_field=fact.path,
                        question=proposal.confirmation_question,
                        explanation=proposal.explanation,
                        confirmed=confirmed,
                    )
                )
                if confirmed:
                    state.resolutions[fact.path] = confirm_resolution(
                        proposal, operator_confirmed=True
                    )
                    state.resolution_operators[fact.path] = self.answers.operator_id

        requests = {
            request.field: request
            for request in self.orchestrator.clarification_requests(state)
            if request.field not in state.candidates
        }
        for field, request in requests.items():
            if field not in self.answers.clarification_answers:
                continue
            raw_answer = self.answers.clarification_answers[field]
            proposal = self._parse_clarification(request, raw_answer)
            if proposal.field != field or proposal.value != raw_answer:
                raise ValueError("clarification proposal changed the operator answer")
            state.candidates[field] = [
                operator_answer_candidate(
                    field=field,
                    value=proposal.value,
                    operator_id=self.answers.operator_id,
                    rationale=proposal.rationale,
                )
            ]
            interactions.append(
                OperatorInteraction(
                    kind="clarification",
                    path_or_field=field,
                    question=proposal.question,
                    explanation=proposal.rationale,
                    confirmed=True,
                )
            )

        self.orchestrator.store.save(state)
        evidence, state = self.orchestrator.run()
        readiness = self.orchestrator.assess(state)
        return OperatorSessionResult(
            evidence=evidence,
            state=state,
            readiness=readiness,
            interactions=tuple(interactions),
        )

    def _propose_resolution(self, fact: MaterialFact) -> ResolutionProposal:
        return self._run(
            prompt_id="conflict-resolution",
            payload={
                "path": fact.path,
                "selected": fact.selected.model_dump(mode="json"),
                "competing": [item.model_dump(mode="json") for item in fact.competing],
            },
            contract=ResolutionProposal,
        )

    def _parse_clarification(
        self, request: ClarificationRequest, raw_answer: JsonValue
    ) -> ClarificationProposal:
        return self._run(
            prompt_id="operator-clarification",
            payload={
                "request": request.model_dump(mode="json"),
                "operator_answer": raw_answer,
            },
            contract=ClarificationProposal,
        )

    def _run(self, *, prompt_id: str, payload: object, contract):  # type: ignore[no-untyped-def]
        value, _ = self.runner.run(
            task=LLMTask.EXTRACTION,
            model=self.model,
            prompt=Prompt(
                id=prompt_id,
                version="1",
                messages=(
                    LLMMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "Assist a drone operator without deciding readiness. Return only "
                            "the requested typed proposal; deterministic code validates it."
                        ),
                    ),
                    LLMMessage(
                        role=MessageRole.USER,
                        content=json.dumps(payload, sort_keys=True),
                    ),
                ),
            ),
            contract=contract,
        )
        return value
