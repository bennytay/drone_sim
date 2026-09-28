from drone_sim.llm_eval import EvaluationCase, EvaluationResult, score
from drone_sim.llm_eval_cli import main


def test_scorecard_measures_extraction_hypothesis_and_ingestion() -> None:
    card = score((EvaluationCase(id="fictional-1", expected_facts=("mass", "wind"), expected_mechanisms=("wind_limit",), expected_ir_fields=("vehicle",), files_opened=2),), (EvaluationResult(id="fictional-1", proposed_facts=("mass", "invented"), anchored_facts=("mass",), proposed_mechanisms=("wind_limit", "wind_limit"), grounded_mechanisms=("wind_limit",), resolved_ir_fields=("vehicle",), files_opened=3),), prompt_id="extract", prompt_version="1", model="replay")
    assert card.extraction_precision == 0.5
    assert card.extraction_recall == 0.5
    assert card.anchor_accuracy == 1
    assert card.mechanism_coverage == 1
    assert card.duplicate_rate == 0.5
    assert card.mean_files_opened == 3


def test_replay_scorecard_cli_prints_baseline_comparison(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["benchmarks/llm_baseline.json"]) == 0
    assert '"extraction_precision": 1.0' in capsys.readouterr().out
