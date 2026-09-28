"""Persisted, evidence-bounded operator session for a drone deployment folder.

The session is deliberately an orchestration layer: reconstruction, planning,
execution, and result judging remain in their deterministic components.  A
hosted LLM may later draft text from ``SessionSummary`` only; it is never given
authority to create a test, alter a result, or issue a readiness verdict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from drone_sim.golden_path import GoldenPathResult, _verdict_line, run_golden_path
from drone_sim.hypothesis import HypothesisGenerationContract, HypothesisStatus
from drone_sim.ir import StrictModel


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
    completed: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _demo_replay() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "demo_hypotheses.json"


def _read_answers(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("answers file must contain a JSON object")
    return value


def _review_hypotheses(
    source: Path, answers: dict[str, object], output: Path
) -> HypothesisGenerationContract:
    contract = HypothesisGenerationContract.model_validate_json(source.read_text())
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


def _state_path(work_dir: Path) -> Path:
    return work_dir / "agent_session.json"


def _save(state: AgentSessionState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2) + "\n")


def run_agent_session(
    root: Path,
    work_dir: Path,
    *,
    answers_path: Path | None = None,
    replay_hypotheses: Path | None = None,
    fresh: bool = False,
) -> tuple[AgentSessionState, GoldenPathResult]:
    """Run or resume one offline/replay agent session and persist its trace."""

    root = root.resolve(strict=True)
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(root):
        raise ValueError("work directory must be outside the read-only deployment folder")
    answers = _read_answers(answers_path)
    replay = replay_hypotheses or (_demo_replay() if root.name == "demo_deployment" else None)
    if replay is None:
        raise ValueError("no replay hypotheses supplied; use --replay-hypotheses for offline sessions")
    replay = replay.resolve(strict=True)
    reviewed_path = work_dir / "reviewed_hypotheses.json"
    reviewed = _review_hypotheses(replay, answers, reviewed_path)

    questions = tuple(
        SessionQuestion(
            id=f"clarification-{index}", question=request.question, field=request.field,
            answer=(answers.get("clarifications", {}) or {}).get(request.field)
            if isinstance(answers.get("clarifications", {}), dict) else None,
        )
        for index, request in enumerate((), start=1)
    )
    # The reconstruction supplies questions after it has inspected the folder.
    result = run_golden_path(root, work_dir, reviewed_path, fresh=fresh)
    questions = tuple(
        SessionQuestion(
            id=f"clarification-{index}", question=request.question, field=request.field,
            answer=(answers.get("clarifications", {}) or {}).get(request.field)
            if isinstance(answers.get("clarifications", {}), dict) else None,
        )
        for index, request in enumerate(result.clarifications, start=1)
    )
    events = [
        SessionEvent(timestamp=_now(), stage="context", message=f"Examined {result.files_indexed} files."),
        SessionEvent(timestamp=_now(), stage="facts", message=f"Extracted {len(result.evidence.facts) if result.evidence else 0} anchored material facts."),
    ]
    events.extend(
        SessionEvent(timestamp=_now(), stage="hypothesis", message=f"{hypothesis.id}: {' -> '.join(hypothesis.causal_path)}")
        for hypothesis in reviewed.hypotheses if hypothesis.status != HypothesisStatus.REJECTED
    )
    events.extend(
        SessionEvent(timestamp=_now(), stage="evaluation", message=f"{run.hypothesis_id}: {_verdict_line(run)}")
        for run in result.runs
    )
    summary = SessionSummary(
        deployment_id=result.evidence.deployment.deployment_id if result.evidence else None,
        hypotheses_considered=len([h for h in reviewed.hypotheses if h.status != HypothesisStatus.REJECTED]),
        evaluations_run=len(result.runs),
        evaluation_outcomes=tuple(f"{run.hypothesis_id}: {_verdict_line(run)}" for run in result.runs),
        limitations=(
            "This evidence-bound summary is not a deployment readiness verdict.",
            "Results are limited to executed providers and nominal conditions.",
        ),
    )
    state = AgentSessionState(root=str(root), events=tuple(events), questions=questions, summary=summary, completed=not result.stopped_at_context)
    _save(state, _state_path(work_dir))
    return state, result


def render_agent_session(state: AgentSessionState, result: GoldenPathResult) -> str:
    lines = ["Drone deployment verification — Agent session", f"Deployment folder: {state.root}"]
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
