import json
from pathlib import Path

from drone_sim.agent_session import run_agent_session
from drone_sim.golden_path import main


EXAMPLES = Path(__file__).parents[1] / "examples"
DEMO = EXAMPLES / "demo_deployment"


def test_agent_session_runs_demo_offline_and_persists_readable_trace(tmp_path: Path) -> None:
    state, result = run_agent_session(DEMO, tmp_path)

    assert result.readiness.ready
    assert state.completed
    assert state.summary is not None
    assert state.summary.label == "NOT A READINESS VERDICT"
    assert state.summary.evaluations_run == 3
    assert (tmp_path / "agent_session.json").exists()
    assert any(event.stage == "facts" for event in state.events)
    assert any(event.stage == "evaluation" for event in state.events)


def test_answers_file_can_reject_a_hypothesis_before_investigation(tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"hypotheses": {"hyp_roof_clearance": "reject"}}))

    state, result = run_agent_session(DEMO, tmp_path / "session", answers_path=answers)

    assert state.summary is not None
    assert state.summary.hypotheses_considered == 2
    assert {run.hypothesis_id for run in result.runs} == {"hyp_energy_reserve", "hyp_takeoff_mass"}


def test_agent_cli_uses_demo_replay_without_an_api_key(tmp_path: Path, capsys) -> None:
    code = main(["agent", str(DEMO), "--work-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert code == 0
    assert "NOT A READINESS VERDICT" in output
    assert "[evaluation]" in output
