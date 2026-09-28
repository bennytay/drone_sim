"""Deterministic policy for iterative drone-hypothesis investigation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from drone_sim.coverage import CoverageMap, Materiality
from drone_sim.hypothesis import FailureHypothesis, HypothesisStatus
from drone_sim.ir import StrictModel


class ResultKind(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    DISAGREEMENT = "disagreement"


class ActionKind(StrEnum):
    TEST = "test"
    ESCALATE = "escalate"
    REFINE = "refine"
    FOLLOW_UP = "follow_up"
    RESOLVE = "resolve"
    REJECT = "reject"


class TestResult(StrictModel):
    __test__ = False
    hypothesis_id: str
    kind: ResultKind
    summary: str = Field(min_length=1)
    fidelity: int = Field(ge=0)
    follow_up_mechanism_id: str | None = None


class InvestigationAction(StrictModel):
    kind: ActionKind
    hypothesis_id: str
    reason: str
    fidelity: int = Field(ge=0)


class InvestigationState(StrictModel):
    hypotheses: tuple[FailureHypothesis, ...]
    results: tuple[TestResult, ...] = ()
    coverage: CoverageMap


_RANK = {
    Materiality.LOW: 1,
    Materiality.MEDIUM: 2,
    Materiality.HIGH: 3,
    Materiality.CRITICAL: 4,
}


def next_action(state: InvestigationState) -> InvestigationAction | None:
    by_id = {r.hypothesis_id: r for r in state.results}
    candidates = [
        h
        for h in state.hypotheses
        if h.status in {HypothesisStatus.PROPOSED, HypothesisStatus.INVESTIGATING}
    ]
    if not candidates:
        return None
    h = max(candidates, key=lambda x: (_RANK[x.materiality], x.uncertainty.value))
    result = by_id.get(h.id)
    if result is None:
        return InvestigationAction(
            kind=ActionKind.TEST,
            hypothesis_id=h.id,
            reason="Highest material unresolved hypothesis.",
            fidelity=0,
        )
    if result.kind in {ResultKind.INCONCLUSIVE, ResultKind.DISAGREEMENT}:
        return InvestigationAction(
            kind=ActionKind.ESCALATE,
            hypothesis_id=h.id,
            reason="Result is uncertain or contradictory; increase fidelity.",
            fidelity=result.fidelity + 1,
        )
    if result.follow_up_mechanism_id:
        return InvestigationAction(
            kind=ActionKind.FOLLOW_UP,
            hypothesis_id=h.id,
            reason="Observed result suggests a new causal mechanism.",
            fidelity=result.fidelity,
        )
    return InvestigationAction(
        kind=ActionKind.RESOLVE
        if result.kind == ResultKind.PASS
        else ActionKind.REFINE,
        hypothesis_id=h.id,
        reason="Judge result supports resolution or boundary refinement.",
        fidelity=result.fidelity,
    )


def apply_result(state: InvestigationState, result: TestResult) -> InvestigationState:
    hypotheses = []
    for h in state.hypotheses:
        if h.id != result.hypothesis_id:
            hypotheses.append(h)
            continue
        status = (
            HypothesisStatus.RESOLVED
            if result.kind == ResultKind.PASS
            else HypothesisStatus.INVESTIGATING
        )
        hypotheses.append(h.model_copy(update={"status": status}))
    return state.model_copy(
        update={"hypotheses": tuple(hypotheses), "results": (*state.results, result)}
    )
