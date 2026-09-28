"""Replay tests for the contract-validated LLM edge."""

from __future__ import annotations

from collections import deque

import pytest

from drone_sim.llm import (
    LLMConfig,
    LLMMessage,
    LLMResponse,
    LLMTask,
    LLMUnavailableError,
    MessageRole,
    Prompt,
    StructuredOutputError,
    StructuredOutputRunner,
    ToolDefinition,
)
from drone_sim.provenance import ConflictResolution, ResolutionMethod


class ReplayProvider:
    def __init__(self, responses: list[str]):
        self.responses = deque(responses)
        self.requests = []

    def complete(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=self.responses.popleft(),
            provider_request_id="replay",
        )


def prompt() -> Prompt:
    return Prompt(
        id="resolve_conflict",
        version="1.2.0",
        messages=(LLMMessage(role=MessageRole.USER, content="Resolve the evidence conflict."),),
    )


def valid_resolution() -> str:
    return '{"method":"operator_decision","selected_candidate_id":"cand_current","rejected_candidate_ids":["cand_stale"],"rationale":"Operator confirmed current source."}'


def test_replay_validates_an_existing_pydantic_contract() -> None:
    provider = ReplayProvider([valid_resolution()])

    value, response = StructuredOutputRunner(provider).run(
        task=LLMTask.EXTRACTION, model="replay-model", prompt=prompt(), contract=ConflictResolution
    )

    assert value.method == ResolutionMethod.OPERATOR_DECISION
    assert response.provider_request_id == "replay"
    assert response.prompt_id == "resolve_conflict"
    assert response.prompt_version == "1.2.0"
    assert provider.requests[0].prompt.id == "resolve_conflict"
    assert provider.requests[0].prompt.version == "1.2.0"


def test_replay_repairs_invalid_contract_output() -> None:
    provider = ReplayProvider(['{"method":"operator_decision"}', valid_resolution()])

    value, _response = StructuredOutputRunner(provider, max_repairs=1).run(
        task=LLMTask.EXTRACTION,
        model="replay-model",
        prompt=prompt(),
        contract=ConflictResolution,
        tools=(ToolDefinition(name="read_evidence", description="Read bounded evidence.", input_schema={"type": "object"}),),
    )

    assert value.selected_candidate_id == "cand_current"
    assert len(provider.requests) == 2
    assert "Validation errors:" in provider.requests[1].prompt.messages[-1].content
    assert provider.requests[1].tools[0].name == "read_evidence"


def test_replay_fails_closed_after_bounded_repairs() -> None:
    provider = ReplayProvider(['{}', '{}', '{}'])

    with pytest.raises(StructuredOutputError, match="ConflictResolution"):
        StructuredOutputRunner(provider, max_repairs=2).run(
            task=LLMTask.EXTRACTION, model="replay-model", prompt=prompt(), contract=ConflictResolution
        )

    assert len(provider.requests) == 3


def test_config_clearly_reports_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        LLMConfig.from_env()


def test_config_selects_a_model_per_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DRONE_SIM_LLM_EXTRACTION_MODEL", "small")
    monkeypatch.setenv("DRONE_SIM_LLM_HYPOTHESIS_MODEL", "large")

    config = LLMConfig.from_env()

    assert config.model_for(LLMTask.EXTRACTION) == "small"
    assert config.model_for(LLMTask.HYPOTHESIS_REASONING) == "large"
