"""Run a committed replay evaluation scorecard and compare it with a baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drone_sim.llm_eval import EvaluationCase, EvaluationResult, score
from drone_sim.llm import (
    AnthropicProvider,
    LLMConfig,
    LLMError,
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, help="Persist this scorecard for comparison")
    parser.add_argument("--model", help="Override the evaluated model identity")
    parser.add_argument("--prompt-version", help="Override the evaluated prompt version")
    parser.add_argument("--live", action="store_true", help="Run fixture inputs against the configured hosted model")
    args = parser.parse_args(argv)
    document = json.loads(args.fixture.read_text())
    cases = tuple(EvaluationCase.model_validate(case) for case in document["cases"])
    model = args.model or document["model"]
    prompt_version = args.prompt_version or document["prompt_version"]
    if args.live:
        try:
            config = LLMConfig.from_env()
        except LLMError as error:
            print(f"drone-llm-eval: {error}", file=sys.stderr)
            return 1
        model = args.model or config.hypothesis_model
        runner = StructuredOutputRunner(AnthropicProvider(config))
        live_results = []
        for raw_case in document["cases"]:
            if "input" not in raw_case:
                raise ValueError(f"live evaluation case {raw_case['id']} has no input")
            result, _ = runner.run(
                task=LLMTask.HYPOTHESIS_REASONING,
                model=model,
                prompt=Prompt(
                    id=document["prompt_id"],
                    version=prompt_version,
                    messages=(LLMMessage(role=MessageRole.USER, content=(
                        "Evaluate this fictional drone ingestion case and return only an EvaluationResult JSON object. Schema: "
                        + json.dumps(EvaluationResult.model_json_schema())
                        + " Input: " + json.dumps(raw_case["input"])
                    )),),
                ),
                contract=EvaluationResult,
            )
            live_results.append(result)
        results = tuple(live_results)
    else:
        results = tuple(EvaluationResult.model_validate(result) for result in document["results"])
    card = score(
        cases,
        results,
        prompt_id=document["prompt_id"],
        prompt_version=prompt_version,
        model=model,
    )
    rendered = card.model_dump(mode="json")
    print(json.dumps(rendered, indent=2, sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rendered, indent=2, sort_keys=True) + "\n")
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        changed = {key: {"before": baseline[key], "after": value} for key, value in rendered.items() if key in baseline and baseline[key] != value}
        print(json.dumps({"diff": changed}, indent=2, sort_keys=True))
    return 0
