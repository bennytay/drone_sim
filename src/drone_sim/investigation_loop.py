"""Persistent deterministic skeleton for the agentic hypothesis investigation loop."""
from drone_sim.ir import StrictModel
from drone_sim.investigation import InvestigationAction, InvestigationState, TestResult, apply_result, next_action
class InvestigationTrace(StrictModel):
    actions: tuple[InvestigationAction, ...] = ()
    results: tuple[TestResult, ...] = ()
    stop_reason: str | None = None
def advance(state: InvestigationState, trace: InvestigationTrace, result: TestResult | None = None) -> tuple[InvestigationState, InvestigationTrace]:
    if result is not None:
        state = apply_result(state, result)
        trace = trace.model_copy(update={"results": (*trace.results, result)})
    action = next_action(state)
    if action is None: return state, trace.model_copy(update={"stop_reason": "no_active_hypotheses"})
    return state, trace.model_copy(update={"actions": (*trace.actions, action)})
