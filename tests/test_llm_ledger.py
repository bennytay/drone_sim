"""Persistent replay and budget tests for LLM call auditing."""

from __future__ import annotations

import pytest

from drone_sim.llm import LLMMessage, LLMResponse, LLMTask, MessageRole, Prompt, StructuredOutputRunner
from drone_sim.llm_ledger import (
    BudgetExceededError,
    CallLedger,
    InputReference,
    LedgerMode,
    LedgeredProvider,
    LLMBudget,
    ModelPrice,
    ReplayMissError,
)
from drone_sim.provenance import ConflictResolution


class LiveProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def complete(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return LLMResponse(
            model=request.model, prompt_id=request.prompt.id, prompt_version=request.prompt.version,
            text=self.response, provider_request_id="live-request", input_tokens=10, output_tokens=5,
        )


def prompt() -> Prompt:
    return Prompt(id="ledger_test", version="1", messages=(LLMMessage(role=MessageRole.USER, content="Return JSON."),))


def valid_resolution() -> str:
    return '{"method":"operator_decision","selected_candidate_id":"a","rejected_candidate_ids":["b"],"rationale":"confirmed"}'


def test_live_entry_is_persistent_and_replays_without_a_provider(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "llm-ledger.json"
    references = (InputReference(kind="candidate", identifier="cand_1"), InputReference(kind="file", identifier="route.json", sha256="a" * 64))
    live = LiveProvider(valid_resolution())
    provider = LedgeredProvider(
        live, CallLedger(path), mode=LedgerMode.LIVE, stage="hypothesis_generation",
        input_references=references, context_trace_indices=(2, 7),
        model_prices={"replay-model": ModelPrice(input_per_million_usd=1, output_per_million_usd=2)},
    )

    value, _response = StructuredOutputRunner(provider).run(
        task=LLMTask.HYPOTHESIS_REASONING, model="replay-model", prompt=prompt(), contract=ConflictResolution
    )

    assert value.selected_candidate_id == "a"
    entry = CallLedger(path).entries()[0]
    assert entry.validation_outcome == "valid"
    assert entry.input_references == references
    assert entry.context_trace_indices == (2, 7)
    assert entry.usage.total_tokens == 15
    assert entry.cost_usd == pytest.approx(0.00002)

    replay = LedgeredProvider(None, CallLedger(path), mode=LedgerMode.REPLAY, stage="hypothesis_generation", input_references=references, context_trace_indices=(2, 7))
    replayed, response = StructuredOutputRunner(replay).run(
        task=LLMTask.HYPOTHESIS_REASONING, model="replay-model", prompt=prompt(), contract=ConflictResolution
    )
    assert replayed == value
    assert response.provider_request_id == "live-request"
    assert live.calls == 1
    assert CallLedger(path).entries()[-1].mode == LedgerMode.REPLAY
    assert CallLedger(path).entries()[-1].cost_usd == 0


def test_replay_miss_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = LedgeredProvider(None, CallLedger(tmp_path / "ledger.json"), mode=LedgerMode.REPLAY, stage="extract")

    with pytest.raises(ReplayMissError, match="No recorded"):
        StructuredOutputRunner(provider).run(task=LLMTask.EXTRACTION, model="model", prompt=prompt(), contract=ConflictResolution)


def test_call_budget_produces_explicit_stop_reason(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = LedgeredProvider(LiveProvider(valid_resolution()), CallLedger(tmp_path / "ledger.json"), mode=LedgerMode.LIVE, stage="extract", budget=LLMBudget(max_calls=1))
    runner = StructuredOutputRunner(provider)
    runner.run(task=LLMTask.EXTRACTION, model="model", prompt=prompt(), contract=ConflictResolution)

    with pytest.raises(BudgetExceededError, match="call count 1 reached limit"):
        runner.run(task=LLMTask.EXTRACTION, model="model", prompt=Prompt(id="second", version="1", messages=prompt().messages), contract=ConflictResolution)


def test_identical_live_requests_are_retained_as_separate_audit_entries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ledger = CallLedger(tmp_path / "ledger.json")
    provider = LedgeredProvider(LiveProvider(valid_resolution()), ledger, mode=LedgerMode.LIVE, stage="extract")
    runner = StructuredOutputRunner(provider)

    runner.run(task=LLMTask.EXTRACTION, model="model", prompt=prompt(), contract=ConflictResolution)
    runner.run(task=LLMTask.EXTRACTION, model="model", prompt=prompt(), contract=ConflictResolution)

    first, second = CallLedger(ledger.path).entries()
    assert first.request_hash == second.request_hash
    assert first.id != second.id
