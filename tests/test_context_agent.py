from drone_sim.context_agent import ContextActionKind, ContextPolicy, record_action
from drone_sim.context import DeploymentState
def test_context_policy_stops_explicitly_or_selects_unresolved_field() -> None:
    policy = ContextPolicy()
    assert policy.choose(("/vehicle/mass_kg",), calls_used=0, max_calls=2).field == "vehicle"
    assert policy.choose(("/vehicle/mass_kg",), calls_used=2, max_calls=2).rationale == "budget_exhausted"
    assert policy.choose((), calls_used=0, max_calls=2).kind == ContextActionKind.STOP


def test_agent_action_is_persisted_in_context_trace() -> None:
    state = DeploymentState(root="/tmp/fake")
    action = ContextPolicy().choose(("/vehicle/mass_kg",), calls_used=0, max_calls=2)
    record_action(state, action)
    assert state.trace[-1].field == "vehicle"
    assert "Highest-priority" in state.trace[-1].reason
