import json
from pathlib import Path

from drone_sim.agent_session import run_agent_session
from drone_sim.golden_path import main
from drone_sim.llm_ledger import CallLedger, LedgerMode
from drone_sim.llm_safety import DeploymentLLMPolicy


EXAMPLES = Path(__file__).parents[1] / "examples"
DEMO = EXAMPLES / "demo_deployment"


def test_agent_session_runs_demo_offline_and_persists_readable_trace(tmp_path: Path) -> None:
    state, result = run_agent_session(DEMO, tmp_path)

    assert result.readiness.ready
    assert state.completed
    assert state.summary is not None
    assert state.summary.label == "NOT A READINESS VERDICT"
    assert state.summary.evaluations_run == 1
    assert (tmp_path / "agent_session.json").exists()
    assert (tmp_path / "generated_hypotheses.json").exists()
    assert any(event.stage == "facts" for event in state.events)
    assert any(event.stage == "document" and event.anchor == "operations/battery_spec.md#3-3" for event in state.events)
    assert any(event.stage == "evaluation" for event in state.events)
    assert state.investigation is not None
    assert state.investigation.stop_reason == "no_active_hypotheses"
    entries = CallLedger(tmp_path / "llm_ledger.json").entries()
    assert [entry.stage for entry in entries] == [
        "document_extraction",
        "hypothesis_generation",
        "session_summary",
    ]
    assert all(entry.mode == LedgerMode.REPLAY and entry.cost_usd == 0 for entry in entries)
    assert all(entry.validation_outcome == "valid" for entry in entries)
    assert all(entry.input_references and entry.context_trace_indices for entry in entries)


def test_answers_file_can_reject_a_hypothesis_before_investigation(tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"hypotheses": {"hyp_energy_reserve": "reject"}}))

    state, result = run_agent_session(DEMO, tmp_path / "session", answers_path=answers)

    assert state.summary is not None
    assert state.summary.hypotheses_considered == 0
    assert not result.runs


def test_agent_cli_uses_demo_replay_without_an_api_key(tmp_path: Path, capsys) -> None:
    code = main(["agent", str(DEMO), "--work-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert code == 0
    assert "NOT A READINESS VERDICT" in output
    assert "[evaluation]" in output


def test_live_mode_fails_before_network_without_explicit_key(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    policy = tmp_path / "policy.json"
    policy.write_text(DeploymentLLMPolicy(allow_hosted_llm=True).model_dump_json())

    code = main(["agent", str(DEMO), "--live", "--llm-policy", str(policy), "--work-dir", str(tmp_path / "work")])

    assert code == 1
    assert "set ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_disabled_hosted_policy_runs_deterministic_pipeline_and_sends_nothing(tmp_path: Path) -> None:
    state, result = run_agent_session(DEMO, tmp_path, live=True)

    assert result.readiness.ready
    assert state.completed
    assert state.events[0].stage == "policy"
    assert not (tmp_path / "llm_ledger.json").exists()
