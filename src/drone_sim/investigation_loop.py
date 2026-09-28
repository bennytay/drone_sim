"""Persistent deterministic loop around planning, routing, and stopping."""

from __future__ import annotations

from collections.abc import Callable

from drone_sim.hypothesis import FailureHypothesis
from drone_sim.investigation import (
    InvestigationAction,
    InvestigationState,
    ResultKind,
    TestResult,
    apply_result,
    next_action,
)
from drone_sim.investigation_assistant import InvestigationGuidance
from drone_sim.ir import StrictModel
from drone_sim.routing import Decision, RoutingOutcome
from drone_sim.stopping import StopDecision, StopPolicy, decide_stop

INTERIM_ROUTING_RULE = "interim-routing-outcome-v1"


class InvestigationTrace(StrictModel):
    """Persistable record of every deterministic investigation transition."""

    actions: tuple[InvestigationAction, ...] = ()
    results: tuple[TestResult, ...] = ()
    guidance: tuple[InvestigationGuidance, ...] = ()
    stop: StopDecision | None = None
    stop_reason: str | None = None


def result_from_routing(hypothesis_id: str, outcome: RoutingOutcome) -> TestResult:
    """Use a labelled interim rule until deterministic judges are available."""

    final = outcome.final
    if outcome.disagreements:
        kind = ResultKind.DISAGREEMENT
        summary = "Interim routing rule found cross-fidelity disagreement; human review required."
    elif final.decision == Decision.ACCEPT:
        margins = tuple(
            assessment.margin
            for assessment in final.assessments
            if assessment.margin is not None
        )
        kind = (
            ResultKind.PASS
            if margins and all(margin >= 0 for margin in margins)
            else ResultKind.FAIL
        )
        summary = (
            "Interim routing rule found all threshold margins on the satisfying side."
            if kind == ResultKind.PASS
            else "Interim routing rule found a clear threshold margin on the failing side."
        )
    else:
        kind = ResultKind.INCONCLUSIVE
        summary = "Interim routing rule exhausted credible routing without a conclusive judge result."
    return TestResult(
        hypothesis_id=hypothesis_id,
        kind=kind,
        summary=summary,
        fidelity=final.level,
        terminal=True,
        determination_rule=INTERIM_ROUTING_RULE,
    )


def advance(
    state: InvestigationState,
    trace: InvestigationTrace,
    result: TestResult | None = None,
) -> tuple[InvestigationState, InvestigationTrace]:
    """Apply one externally supplied result and select the next action."""

    if result is not None:
        state = apply_result(state, result)
        trace = trace.model_copy(update={"results": (*trace.results, result)})
    action = next_action(state)
    if action is None:
        return state, trace.model_copy(update={"stop_reason": "no_active_hypotheses"})
    return state, trace.model_copy(update={"actions": (*trace.actions, action)})


def run_investigation(
    state: InvestigationState,
    *,
    route: Callable[[FailureHypothesis, InvestigationAction], RoutingOutcome],
    policy: StopPolicy,
    trace: InvestigationTrace | None = None,
    guidance: Callable[
        [InvestigationState, TestResult, RoutingOutcome], InvestigationGuidance
    ]
    | None = None,
) -> tuple[InvestigationState, InvestigationTrace]:
    """Run selected drone hypotheses until the deterministic stopping policy stops."""

    trace = trace or InvestigationTrace()
    while True:
        action = next_action(state)
        if action is None:
            decision = StopDecision(
                stop=True,
                reason="complete",
                residuals=tuple(
                    f"{entry.mechanism_id}: {entry.state.value}"
                    for entry in state.coverage.unexplored
                ),
                novelty=0.0,
            )
            return state, trace.model_copy(
                update={"stop": decision, "stop_reason": decision.reason.value}
            )
        trace = trace.model_copy(update={"actions": (*trace.actions, action)})
        hypothesis = next(
            item for item in state.hypotheses if item.id == action.hypothesis_id
        )
        outcome = route(hypothesis, action)
        result = result_from_routing(hypothesis.id, outcome)
        state = apply_result(state, result)
        trace = trace.model_copy(update={"results": (*trace.results, result)})
        if guidance is not None:
            proposal = guidance(state, result, outcome)
            trace = trace.model_copy(update={"guidance": (*trace.guidance, proposal)})
        decision = decide_stop(
            state.coverage,
            actions=len(trace.actions),
            novelty=0.0,
            disagreement=result.kind == ResultKind.DISAGREEMENT,
            policy=policy,
        )
        if decision.stop:
            return state, trace.model_copy(
                update={"stop": decision, "stop_reason": decision.reason.value}
            )
