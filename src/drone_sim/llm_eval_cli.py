"""Run a committed replay evaluation scorecard and compare it with a baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from drone_sim.llm_eval import EvaluationCase, EvaluationResult, score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    document = json.loads(args.fixture.read_text())
    card = score(
        tuple(EvaluationCase.model_validate(case) for case in document["cases"]),
        tuple(EvaluationResult.model_validate(result) for result in document["results"]),
        prompt_id=document["prompt_id"], prompt_version=document["prompt_version"], model=document["model"],
    )
    rendered = card.model_dump(mode="json")
    print(json.dumps(rendered, indent=2, sort_keys=True))
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        changed = {key: {"before": baseline[key], "after": value} for key, value in rendered.items() if key in baseline and baseline[key] != value}
        print(json.dumps({"diff": changed}, indent=2, sort_keys=True))
    return 0
