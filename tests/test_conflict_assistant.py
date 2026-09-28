import json
from pathlib import Path

import pytest

from drone_sim.conflict_assistant import (
    OperatorResolutionSession,
    ResolutionProposal,
    confirm_resolution,
    operator_answer_candidate,
)
from drone_sim.llm import LLMResponse, StructuredOutputRunner
from drone_sim.provenance import ResolutionMethod, ValueOrigin


class ReplayAssistant:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        payload = json.loads(request.prompt.messages[-1].content)
        if request.prompt.id == "conflict-resolution":
            selected = payload["selected"]
            competing = payload["competing"]
            result = {
                "method": "operator_decision",
                "selected_candidate_id": selected["id"],
                "rejected_candidate_ids": [item["id"] for item in competing],
                "explanation": "The current approved source outranks the archived source.",
                "rationale": "Operator confirmed the current approved deployment record.",
                "confirmation_question": (
                    f"Confirm {selected['value']!r} for {payload['path']} and reject "
                    "the archived alternative?"
                ),
            }
        else:
            result = {
                "field": payload["request"]["field"],
                "value": payload["operator_answer"],
                "question": payload["request"]["question"],
                "rationale": "Operator supplied and confirmed this deployment fact.",
            }
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=json.dumps(result),
        )


def proposal() -> ResolutionProposal:
    return ResolutionProposal(
        method=ResolutionMethod.OPERATOR_DECISION,
        selected_candidate_id="current",
        rejected_candidate_ids=("stale",),
        explanation="Current approved record is newer.",
        rationale="Operator reviewed source dates.",
        confirmation_question="Use the current approved record?",
    )


def test_only_operator_confirmation_creates_resolution() -> None:
    with pytest.raises(PermissionError):
        confirm_resolution(proposal(), operator_confirmed=False)
    assert (
        confirm_resolution(proposal(), operator_confirmed=True).method
        == ResolutionMethod.OPERATOR_DECISION
    )


def test_scripted_operator_answer_has_observed_provenance() -> None:
    answer = operator_answer_candidate(
        field="vehicle",
        value={"id": "uav"},
        operator_id="operator-1",
        rationale="Operator supplied approved record",
    )
    assert answer.origin == ValueOrigin.OBSERVED
    assert answer.source_path == "operator:operator-1"


@pytest.mark.parametrize(
    ("folder", "expected_calls"),
    [
        ("03_coastal-turbine_conflicting", 2),
        ("04_quarry-mapping_incomplete", 3),
    ],
)
def test_scripted_operator_session_reaches_ready_and_does_not_reask(
    tmp_path: Path, folder: str, expected_calls: int
) -> None:
    replay = ReplayAssistant()
    root = Path("examples/synthetic_deployments") / folder
    answers = Path("examples/operator_answers") / f"{folder}.json"
    state_path = tmp_path / f"{folder}.json"
    first = OperatorResolutionSession(
        root,
        state_path,
        runner=StructuredOutputRunner(replay),
        model="replay",
        answers_path=answers,
    ).run()

    assert first.readiness.status == "ready"
    assert first.evidence is not None
    assert replay.calls == expected_calls
    if "conflicting" in folder:
        assert len(first.state.resolutions) == 2
        assert set(first.state.resolution_operators.values()) == {
            "ci-flight-operator"
        }
        assert all(
            fact.resolution is not None
            for fact in first.evidence.facts
            if fact.competing
        )
    else:
        assert {
            first.state.candidates[field][0].source_path
            for field in ("mission", "autonomy", "success_criteria")
        } == {"operator:ci-flight-operator"}

    second = OperatorResolutionSession(
        root,
        state_path,
        runner=StructuredOutputRunner(replay),
        model="replay",
        answers_path=answers,
    ).run()
    assert second.readiness.status == "ready"
    assert replay.calls == expected_calls
    assert second.interactions == ()


def test_unconfirmed_conflict_remains_blocking(tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "operator_id": "operator-1",
                "conflict_confirmations": {},
                "clarification_answers": {},
            }
        )
    )
    result = OperatorResolutionSession(
        Path("examples/synthetic_deployments/03_coastal-turbine_conflicting"),
        tmp_path / "state.json",
        runner=StructuredOutputRunner(ReplayAssistant()),
        model="replay",
        answers_path=answers,
    ).run()

    assert result.readiness.status == "conflicting"
    assert result.state.resolutions == {}
    assert result.interactions
    assert not any(item.confirmed for item in result.interactions)
