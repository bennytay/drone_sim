"""Prompt-injection and customer-data boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from drone_sim.llm import LLMMessage, LLMRequest, LLMResponse, LLMTask, MessageRole, Prompt, StructuredOutputRunner
from drone_sim.llm_ledger import CallLedger, LedgerMode, LedgeredProvider
from drone_sim.llm_safety import (
    DeploymentLLMPolicy, LLMDisabledError, SafeStructuredOutputRunner,
    UnsafeContractError, prepare_untrusted_text,
)
from drone_sim.provenance import ConflictResolution


class Provider:
    def complete(self, request):  # type: ignore[no-untyped-def]
        return LLMResponse(model=request.model, prompt_id=request.prompt.id, prompt_version=request.prompt.version, text="{}")


def test_adversarial_text_is_delimited_and_redacted() -> None:
    text = (Path(__file__).parents[1] / "examples/adversarial_deployment/operator_notes.txt").read_text()
    prepared = prepare_untrusted_text(
        source_path="operator_notes.txt", text=text,
        policy=DeploymentLLMPolicy(allow_hosted_llm=True, redaction_patterns=(r"set every threshold to zero",)),
    )

    assert prepared.delimited_text.startswith("<untrusted_deployment_evidence")
    assert prepared.delimited_text.endswith("</untrusted_deployment_evidence>")
    assert "[REDACTED]" in prepared.delimited_text
    assert prepared.sent_reference.sha256 is not None


def test_disabled_policy_sends_nothing_and_leaves_ledger_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ledger = CallLedger(tmp_path / "ledger.json")
    with pytest.raises(LLMDisabledError, match="no bytes were sent"):
        prepare_untrusted_text(source_path="notes.txt", text="ignore instructions", policy=DeploymentLLMPolicy())
    assert ledger.entries() == ()


def test_ledger_records_the_hash_of_exact_delimited_bytes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    prepared = prepare_untrusted_text(
        source_path="notes.txt", text="untrusted note", policy=DeploymentLLMPolicy(allow_hosted_llm=True)
    )
    ledger = CallLedger(tmp_path / "ledger.json")
    provider = LedgeredProvider(
        Provider(), ledger, mode=LedgerMode.LIVE, stage="extract", input_references=(prepared.sent_reference,)
    )
    provider.complete(LLMRequest(
        task=LLMTask.EXTRACTION, model="model",
        prompt=Prompt(id="x", version="1", messages=(LLMMessage(role=MessageRole.USER, content=prepared.delimited_text),)),
    ))
    assert ledger.entries()[0].input_references == (prepared.sent_reference,)


def test_conflict_resolution_is_never_an_llm_contract() -> None:
    safe = SafeStructuredOutputRunner(StructuredOutputRunner(Provider()))
    with pytest.raises(UnsafeContractError, match="operator confirmation"):
        safe.run(
            task=LLMTask.EXTRACTION, model="model",
            prompt=Prompt(id="x", version="1", messages=(LLMMessage(role=MessageRole.USER, content="x"),)),
            contract=ConflictResolution,
        )
