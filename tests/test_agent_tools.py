from pathlib import Path
import pytest
from drone_sim.agent_tools import AgentToolRuntime
from drone_sim.context import DeploymentState


def test_scripted_tools_are_bounded_audited_and_traced() -> None:
    root = Path("examples/demo_deployment")
    state = DeploymentState(root=str(root.resolve()))
    tools = AgentToolRuntime(root, state, max_bytes=100_000)
    assert tools.search_files("aircraft")
    parsed = tools.parse_file("aircraft/approved_current_aircraft.json")
    assert parsed["adapter"] == "json"
    assert [entry.name for entry in tools.ledger] == ["search_files", "parse_file"]
    assert state.trace[-1].reason.startswith("agent requested")


def test_out_of_root_and_oversized_requests_fail_closed() -> None:
    root = Path("examples/demo_deployment")
    tools = AgentToolRuntime(root, DeploymentState(root=str(root.resolve())), max_bytes=10)
    with pytest.raises(ValueError):
        tools.parse_file("../../pyproject.toml")
    with pytest.raises(ValueError):
        tools.parse_file("aircraft/approved_current_aircraft.json")
