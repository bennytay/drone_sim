"""Deterministic scorecards for replayed drone-LLM evaluation sets."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    input: JsonValue | None = None
    expected_facts: tuple[str, ...] = ()
    expected_mechanisms: tuple[str, ...] = ()
    expected_ir_fields: tuple[str, ...] = ()
    files_opened: int = 0


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    proposed_facts: tuple[str, ...] = ()
    anchored_facts: tuple[str, ...] = ()
    proposed_mechanisms: tuple[str, ...] = ()
    grounded_mechanisms: tuple[str, ...] = ()
    resolved_ir_fields: tuple[str, ...] = ()
    files_opened: int = 0


class Scorecard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt_id: str
    prompt_version: str
    model: str
    extraction_precision: float = Field(ge=0, le=1)
    extraction_recall: float = Field(ge=0, le=1)
    anchor_accuracy: float = Field(ge=0, le=1)
    false_fact_rate: float = Field(ge=0, le=1)
    mechanism_coverage: float = Field(ge=0, le=1)
    groundedness: float = Field(ge=0, le=1)
    duplicate_rate: float = Field(ge=0, le=1)
    field_accuracy: float = Field(ge=0, le=1)
    mean_files_opened: float = Field(ge=0)


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def score(cases: tuple[EvaluationCase, ...], results: tuple[EvaluationResult, ...], *, prompt_id: str, prompt_version: str, model: str) -> Scorecard:
    by_id = {result.id: result for result in results}
    if set(by_id) != {case.id for case in cases}:
        raise ValueError("evaluation cases and results must have identical IDs")
    expected_facts = proposed_facts = correct_facts = anchored_correct = 0
    expected_mechanisms = covered = proposed_mechanisms = grounded = duplicates = 0
    expected_fields = correct_fields = files = 0
    for case in cases:
        result = by_id[case.id]
        facts, proposals = set(case.expected_facts), list(result.proposed_facts)
        expected_facts += len(facts); proposed_facts += len(proposals); correct_facts += len(facts & set(proposals)); anchored_correct += len(facts & set(result.anchored_facts))
        mechanisms, proposed = set(case.expected_mechanisms), list(result.proposed_mechanisms)
        expected_mechanisms += len(mechanisms); covered += len(mechanisms & set(proposed)); proposed_mechanisms += len(proposed); grounded += len(set(proposed) & set(result.grounded_mechanisms)); duplicates += len(proposed) - len(set(proposed))
        fields = set(case.expected_ir_fields); expected_fields += len(fields); correct_fields += len(fields & set(result.resolved_ir_fields)); files += result.files_opened
    return Scorecard(prompt_id=prompt_id, prompt_version=prompt_version, model=model, extraction_precision=_ratio(correct_facts, proposed_facts), extraction_recall=_ratio(correct_facts, expected_facts), anchor_accuracy=_ratio(anchored_correct, correct_facts), false_fact_rate=_ratio(proposed_facts-correct_facts, proposed_facts), mechanism_coverage=_ratio(covered, expected_mechanisms), groundedness=_ratio(grounded, proposed_mechanisms), duplicate_rate=_ratio(duplicates, proposed_mechanisms), field_accuracy=_ratio(correct_fields, expected_fields), mean_files_opened=files/len(cases))
