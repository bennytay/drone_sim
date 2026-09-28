"""Persisted, evidence-bounded operator session for a drone deployment folder.

The session is deliberately an orchestration layer: reconstruction, planning,
execution, and result judging remain in their deterministic components.  A
hosted LLM may draft text from ``SessionSummary`` only; it is never given
authority to create a test, alter a result, or issue a readiness verdict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from drone_sim.document_extraction import (
    DocumentExtractionResponse,
    extract_document_candidates,
)
from drone_sim.agent_tools import AgentToolRuntime
from drone_sim.context import CandidateFact
from drone_sim.coverage import assess_coverage
from drone_sim.capabilities import DEFAULT_CAPABILITY_ONTOLOGY
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.golden_path import GoldenPathResult, _verdict_line, run_golden_path
from drone_sim.hypothesis import HypothesisGenerationContract, HypothesisStatus
from drone_sim.ir import StrictModel
from drone_sim.llm import (
    AnthropicProvider,
    LLMConfig,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)
from drone_sim.hypothesis_generator import HypothesisProposalBatch, generate_hypotheses
from drone_sim.investigation_loop import InvestigationTrace
from drone_sim.knowledge_retrieval import retrieve_knowledge
from drone_sim.llm_safety import DeploymentLLMPolicy, prepare_untrusted_text
from drone_sim.llm_ledger import (
    CallLedger,
    InputReference,
    LedgerMode,
    LedgeredProvider,
)


class SessionEvent(StrictModel):
    timestamp: datetime
    stage: str
    message: str
    anchor: str | None = None


class SessionQuestion(StrictModel):
    id: str
    question: str
    field: str
    answer: str | None = None


class SessionSummary(StrictModel):
    """Structured facts a summary writer may restate, but never extend."""

    label: Literal["NOT A READINESS VERDICT"] = "NOT A READINESS VERDICT"
    deployment_id: str | None = None
    hypotheses_considered: int = 0
    evaluations_run: int = 0
    evaluation_outcomes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class AgentSessionState(StrictModel):
    version: str = "0.1.0"
    root: str
    events: tuple[SessionEvent, ...] = ()
    questions: tuple[SessionQuestion, ...] = ()
    summary: SessionSummary | None = None
    investigation: InvestigationTrace | None = None
    document_candidates: tuple[CandidateFact, ...] = ()
    completed: bool = False


class SessionReplay(StrictModel):
    """Versioned responses for CI; each follows the same LLM contract as live mode."""

    document_proposals: tuple[dict[str, object], ...]
    hypotheses: HypothesisGenerationContract
    summary: SessionSummary


class ReplayProvider:
    def __init__(self, replay: SessionReplay) -> None:
        self.replay = replay

    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.task == LLMTask.EXTRACTION:
            value: object = {"proposals": self.replay.document_proposals}
        elif request.prompt.id == "session-summary":
            marker = "\nResult:\n"
            content = request.prompt.messages[-1].content
            if marker not in content:
                raise ValueError("replay summary prompt has no structured result")
            value = json.loads(content.rsplit(marker, 1)[1])
        else:
            value = self.replay.hypotheses.model_dump(mode="json")
        text = json.dumps(value)
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=text,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _demo_replay() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "replays" / "demo_agent_replay.json"


def _read_answers(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("answers file must contain a JSON object")
    return value


def _review_hypotheses_from_contract(
    contract: HypothesisGenerationContract, answers: dict[str, object], output: Path
) -> HypothesisGenerationContract:
    decisions = answers.get("hypotheses", {})
    if not isinstance(decisions, dict):
        raise ValueError("answers.hypotheses must be an object mapping ID to accept or reject")
    reviewed = []
    for hypothesis in contract.hypotheses:
        decision = decisions.get(hypothesis.id, "accept")
        if decision not in {"accept", "reject"}:
            raise ValueError(f"invalid review decision for {hypothesis.id}: {decision}")
        reviewed.append(
            hypothesis.model_copy(update={"status": HypothesisStatus.REJECTED})
            if decision == "reject"
            else hypothesis
        )
    reviewed_contract = contract.model_copy(update={"hypotheses": tuple(reviewed)})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(reviewed_contract.model_dump_json(indent=2) + "\n")
    return reviewed_contract


def _prompt(identifier: str, content: str) -> Prompt:
    return Prompt(
        id=identifier,
        version="1",
        messages=(
            LLMMessage(
                role=MessageRole.SYSTEM,
                content=(
                    "Return only JSON for the requested typed contract. "
                    "Do not issue a readiness verdict."
                ),
            ),
            LLMMessage(role=MessageRole.USER, content=content),
        ),
    )


def _runners(
    replay_path: Path | None,
    live: bool,
    *,
    ledger_path: Path,
    input_references: tuple[InputReference, ...],
    context_trace_indices: tuple[int, ...],
) -> tuple[StructuredOutputRunner, StructuredOutputRunner, StructuredOutputRunner, str, str]:
    ledger = CallLedger(ledger_path)
    if live:
        config = LLMConfig.from_env()
        provider = AnthropicProvider(config)
        return (
            StructuredOutputRunner(LedgeredProvider(provider, ledger, mode=LedgerMode.LIVE, stage="document_extraction", input_references=input_references, context_trace_indices=context_trace_indices)),
            StructuredOutputRunner(LedgeredProvider(provider, ledger, mode=LedgerMode.LIVE, stage="hypothesis_generation", input_references=input_references, context_trace_indices=context_trace_indices)),
            StructuredOutputRunner(LedgeredProvider(provider, ledger, mode=LedgerMode.LIVE, stage="session_summary", input_references=input_references, context_trace_indices=context_trace_indices)),
            config.extraction_model,
            config.hypothesis_model,
        )
    if replay_path is None:
        replay_path = _demo_replay()
    replay = SessionReplay.model_validate_json(replay_path.read_text())
    source = ReplayProvider(replay)
    def replay_runner(stage: str) -> StructuredOutputRunner:
        return StructuredOutputRunner(
            LedgeredProvider(
                None,
                ledger,
                mode=LedgerMode.REPLAY,
                stage=stage,
                input_references=input_references,
                context_trace_indices=context_trace_indices,
                replay_provider=source,
            )
        )
    return (
        replay_runner("document_extraction"),
        replay_runner("hypothesis_generation"),
        replay_runner("session_summary"),
        "replay",
        "replay",
    )


def _state_path(work_dir: Path) -> Path:
    return work_dir / "agent_session.json"


def _save(state: StrictModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2) + "\n")


def run_agent_session(
    root: Path,
    work_dir: Path,
    *,
    answers_path: Path | None = None,
    replay_path: Path | None = None,
    live: bool = False,
    llm_policy: DeploymentLLMPolicy = DeploymentLLMPolicy(),
    fresh: bool = False,
) -> tuple[AgentSessionState, GoldenPathResult]:
    """Run or resume one offline/replay agent session and persist its trace."""

    root = root.resolve(strict=True)
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(root):
        raise ValueError("work directory must be outside the read-only deployment folder")
    answers = _read_answers(answers_path)
    document_events: list[SessionEvent] = []
    document_candidates: tuple[CandidateFact, ...] = ()
    usable_energy_wh: float | None = None
    if not live and replay_path is None and root.name != "demo_deployment":
        raise ValueError("no replay supplied; use --replay FILE for offline sessions")
    if replay_path is not None:
        replay_path = replay_path.resolve(strict=True)
    # Reconstruct before the agent sees any deployment data. This is also the
    # resume boundary: context state is deterministic and persisted separately.
    preliminary = run_golden_path(root, work_dir, fresh=fresh)
    tool_runtime = AgentToolRuntime(
        root,
        preliminary.state,
        ledger_path=work_dir / "tool_ledger.json",
        state_path=work_dir / "state.json",
    )
    tool_runtime.list_index()
    tool_runtime.search_files("battery specification")
    if (root / "operations" / "battery_spec.md").exists():
        tool_runtime.parse_file("operations/battery_spec.md")
        tool_runtime.read_text_span("operations/battery_spec.md", 1, 5)
    if live and not llm_policy.allow_hosted_llm:
        state = AgentSessionState(
            root=str(root),
            events=(
                SessionEvent(
                    timestamp=_now(),
                    stage="policy",
                    message="Hosted LLM calls are disabled; deterministic context and applicability completed without sending customer bytes.",
                ),
            ),
            summary=SessionSummary(
                deployment_id=(
                    preliminary.evidence.deployment.deployment_id
                    if preliminary.evidence else None
                ),
                limitations=(
                    "Hosted LLM calls were disabled by deployment policy.",
                    "No hypotheses or deployment readiness verdict were produced.",
                ),
            ),
            completed=True,
        )
        _save(state, _state_path(work_dir))
        return state, preliminary
    file_references = tuple(
        InputReference(
            kind="deployment_file",
            identifier=path,
            sha256=source.sha256,
        )
        for path, source in sorted(preliminary.state.parsed_sources.items())
    )
    trace_indices = tuple(range(len(preliminary.state.trace)))
    extraction_runner, hypothesis_runner, summary_runner, extraction_model, reasoning_model = _runners(
        replay_path,
        live,
        ledger_path=work_dir / "llm_ledger.json",
        input_references=file_references,
        context_trace_indices=trace_indices,
    )
    if preliminary.evidence is None or preliminary.stopped_at_context:
        result = preliminary
        reviewed = HypothesisGenerationContract(hypotheses=())
    else:
        document_path = root / "operations" / "battery_spec.md"
        if document_path.exists():
            source_bytes = document_path.read_bytes()
            prepared = prepare_untrusted_text(
                source_path="operations/battery_spec.md",
                text=source_bytes.decode("utf-8"),
                policy=(
                    llm_policy
                    if live
                    else DeploymentLLMPolicy(
                        allow_hosted_llm=True,
                        redaction_patterns=llm_policy.redaction_patterns,
                    )
                ),
            )
            extracted = extract_document_candidates(
                runner=extraction_runner, model=extraction_model,
                prompt=_prompt(
                    "document-extraction",
                    "Extract supported deployment facts using this JSON Schema:\n"
                    + json.dumps(DocumentExtractionResponse.model_json_schema())
                    + "\nEvidence:\n" + prepared.delimited_text,
                ),
                field="constraints", source_bytes=source_bytes,
            )
            document_candidates = extracted
            if extracted and isinstance(extracted[0].value, int | float):
                usable_energy_wh = float(extracted[0].value)
            document_events = [
                SessionEvent(
                    timestamp=_now(),
                    stage="document",
                    message=(
                        f"Verified document fact {item.value} from "
                        f"{item.source_path}#{item.source_location}."
                    ),
                    anchor=f"{item.source_path}#{item.source_location}",
                )
                for item in extracted
            ]
        prepared_ir = prepare_untrusted_text(
            source_path="evidence.json",
            text=preliminary.evidence.model_dump_json(),
            policy=(
                llm_policy
                if live
                else DeploymentLLMPolicy(
                    allow_hosted_llm=True,
                    redaction_patterns=llm_policy.redaction_patterns,
                )
            ),
        )
        initial_coverage = assess_coverage(preliminary.evidence.deployment)
        knowledge = retrieve_knowledge(
            root,
            model_world_prompts=(
                "Multirotor energy reserve and obstacle clearance deserve explicit hypotheses when route, loading, and site evidence make them applicable.",
            ),
        )
        _save(knowledge, work_dir / "knowledge_bundle.json")
        generation = generate_hypotheses(
            runner=hypothesis_runner, model=reasoning_model,
            evidence=preliminary.evidence,
            coverage=initial_coverage,
            knowledge=knowledge,
            prompt=_prompt(
                "hypothesis-generation",
                "Propose drone-only failure hypotheses using this JSON Schema:\n"
                + json.dumps(HypothesisProposalBatch.model_json_schema())
                + "\nEvidence:\n" + prepared_ir.delimited_text
                + "\nCoverage:\n" + initial_coverage.model_dump_json()
                + "\nTaxonomy:\n" + DEFAULT_FAILURE_TAXONOMY.model_dump_json()
                + "\nCapability ontology:\n" + DEFAULT_CAPABILITY_ONTOLOGY.model_dump_json()
                + "\nKnowledge bundle:\n" + knowledge.model_dump_json(),
            ),
        )
        generated = generation.contract
        _save(generation, work_dir / "hypothesis_generation_audit.json")
        generated_path = work_dir / "generated_hypotheses.json"
        reviewed = _review_hypotheses_from_contract(generated, answers, generated_path)
        result = run_golden_path(
            root, work_dir, generated_path, usable_energy_wh=usable_energy_wh
        )
    questions = tuple(
        SessionQuestion(
            id=f"clarification-{index}", question=request.question, field=request.field,
            answer=(answers.get("clarifications", {}) or {}).get(request.field)
            if isinstance(answers.get("clarifications", {}), dict) else None,
        )
        for index, request in enumerate(result.clarifications, start=1)
    )
    events = [
        SessionEvent(
            timestamp=_now(),
            stage="context",
            message=f"Examined {result.files_indexed} files.",
        ),
        SessionEvent(
            timestamp=_now(),
            stage="facts",
            message=(
                f"Extracted {len(result.evidence.facts) if result.evidence else 0} "
                "anchored material facts."
            ),
        ),
    ]
    events.extend(
        document_events
        if preliminary.evidence is not None and not preliminary.stopped_at_context
        else []
    )
    events.extend(
        SessionEvent(
            timestamp=_now(),
            stage="hypothesis",
            message=f"{hypothesis.id}: {' -> '.join(hypothesis.causal_path)}",
        )
        for hypothesis in reviewed.hypotheses
        if hypothesis.status != HypothesisStatus.REJECTED
    )
    events.extend(
        SessionEvent(
            timestamp=_now(),
            stage="evaluation",
            message=f"{run.hypothesis_id}: {_verdict_line(run)}",
        )
        for run in result.runs
    )
    draft_summary = SessionSummary(
        deployment_id=result.evidence.deployment.deployment_id if result.evidence else None,
        hypotheses_considered=len(
            [h for h in reviewed.hypotheses if h.status != HypothesisStatus.REJECTED]
        ),
        evaluations_run=len(result.runs),
        evaluation_outcomes=tuple(f"{run.hypothesis_id}: {_verdict_line(run)}" for run in result.runs),
        limitations=(
            "This evidence-bound summary is not a deployment readiness verdict.",
            "Results are limited to executed providers and nominal conditions.",
        ),
    )
    if result.runs:
        summary, _ = summary_runner.run(
            task=LLMTask.HYPOTHESIS_REASONING,
            model=reasoning_model,
            prompt=_prompt(
                "session-summary",
                "Restate exactly this structured result using the same JSON Schema; do not add claims:\n"
                + json.dumps(SessionSummary.model_json_schema())
                + "\nResult:\n" + draft_summary.model_dump_json(),
            ),
            contract=SessionSummary,
        )
        if summary != draft_summary:
            raise ValueError(
                "summary response made claims outside the structured result envelope: "
                f"{summary.model_dump()} != {draft_summary.model_dump()}"
            )
    else:
        summary = draft_summary

    state = AgentSessionState(
        root=str(root),
        events=tuple(events),
        questions=questions,
        summary=summary,
        investigation=result.investigation,
        document_candidates=document_candidates,
        completed=not result.stopped_at_context,
    )
    _save(state, _state_path(work_dir))
    return state, result


def render_agent_session(state: AgentSessionState, result: GoldenPathResult) -> str:
    lines = [
        "Drone deployment verification — Agent session",
        f"Deployment folder: {state.root}",
    ]
    lines.extend(f"[{event.stage}] {event.message}" for event in state.events)
    for question in state.questions:
        answer = question.answer or "unanswered"
        lines.append(f"[question] {question.question} ({question.field}: {answer})")
    assert state.summary is not None
    lines.append("")
    lines.append(state.summary.label)
    lines.extend(f"- {outcome}" for outcome in state.summary.evaluation_outcomes)
    lines.extend(f"- limitation: {item}" for item in state.summary.limitations)
    lines.append(f"Session state: {result.work_dir / 'agent_session.json'}")
    return "\n".join(lines)
