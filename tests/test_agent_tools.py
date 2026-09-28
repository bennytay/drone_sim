from pathlib import Path
import json
import pytest
from drone_sim.agent_tools import AgentToolRuntime, TOOL_DEFINITIONS
from drone_sim.context import DeploymentState


def test_scripted_tools_are_bounded_audited_and_traced() -> None:
    root = Path("examples/demo_deployment")
    state = DeploymentState(root=str(root.resolve()))
    tools = AgentToolRuntime(root, state, max_bytes=100_000)
    assert tools.search_files("aircraft")
    parsed = tools.parse_file("aircraft/approved_current_aircraft.json")
    assert parsed["adapter"] == "json"
    assert [entry.name for entry in tools.ledger] == ["search_files", "parse_file"]
    assert state.trace[-1].reason.startswith("agent called")


def test_registry_exposes_schemas_and_persists_every_call(tmp_path: Path) -> None:
    root = Path("examples/demo_deployment")
    state = DeploymentState(root=str(root.resolve()))
    ledger = tmp_path / "tools.json"
    tools = AgentToolRuntime(root, state, ledger_path=ledger)

    tools.list_index()
    assert "Usable battery energy" in tools.read_text_span("operations/battery_spec.md", 1, 5)
    assert tools.taxonomy_lookup("energy_battery.reserve.route_demand")["id"]

    assert {definition.name for definition in TOOL_DEFINITIONS} >= {"list_index", "read_text_span", "taxonomy_lookup"}
    assert len(json.loads(ledger.read_text())) == 3
    assert len(state.trace) == 3


def test_out_of_root_and_oversized_requests_fail_closed() -> None:
    root = Path("examples/demo_deployment")
    tools = AgentToolRuntime(root, DeploymentState(root=str(root.resolve())), max_bytes=10)
    with pytest.raises(ValueError):
        tools.parse_file("../../pyproject.toml")
    with pytest.raises(ValueError):
        tools.parse_file("aircraft/approved_current_aircraft.json")
