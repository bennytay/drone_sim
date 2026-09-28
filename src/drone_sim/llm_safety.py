"""Safety boundary for untrusted drone-deployment content sent to an LLM."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.llm import Contract, LLMError, LLMTask, Prompt, StructuredOutputRunner, ToolDefinition
from drone_sim.llm_ledger import InputReference
from drone_sim.provenance import ConflictResolution, EvidenceCandidate, ValueOrigin


class LLMDisabledError(LLMError):
    """No call is permitted for this deployment under its explicit policy."""


class UnsafeContractError(LLMError):
    """Model output cannot be used for judgments or conflict selection."""


class DeploymentLLMPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_hosted_llm: bool = False
    redaction_patterns: tuple[str, ...] = ()


class PreparedUntrustedText(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delimited_text: str
    sent_reference: InputReference


def prepare_untrusted_text(
    *, source_path: str, text: str, policy: DeploymentLLMPolicy
) -> PreparedUntrustedText:
    """Redact then delimit evidence so content cannot alter system instructions."""
    if not policy.allow_hosted_llm:
        raise LLMDisabledError("LLM calls are disabled for this deployment; no bytes were sent")
    redacted = text
    for pattern in policy.redaction_patterns:
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    body = f"<untrusted_deployment_evidence source={source_path!r}>\n{redacted}\n</untrusted_deployment_evidence>"
    encoded = body.encode("utf-8")
    return PreparedUntrustedText(
        delimited_text=body,
        sent_reference=InputReference(
            kind="sent_untrusted_text", identifier=source_path,
            sha256=hashlib.sha256(encoded).hexdigest(),
        ),
    )


def validate_inferred_evidence(candidate: EvidenceCandidate, source_bytes: bytes) -> EvidenceCandidate:
    """Accept only model proposals anchored to the exact inspected source bytes."""
    if candidate.origin != ValueOrigin.INFERRED:
        raise ValueError("LLM-proposed evidence must have origin=inferred")
    expected = hashlib.sha256(source_bytes).hexdigest()
    if not candidate.sources or any(anchor.sha256 != expected for anchor in candidate.sources):
        raise ValueError("LLM-proposed evidence requires an exact source anchor matching source bytes")
    return candidate


AllowedContract = TypeVar("AllowedContract", bound=BaseModel)


class SafeStructuredOutputRunner:
    """Disallow contracts that could let a model directly make a core decision."""

    def __init__(self, runner: StructuredOutputRunner):
        self._runner = runner

    def run(
        self, *, task: LLMTask, model: str, prompt: Prompt, contract: type[AllowedContract], tools: tuple[ToolDefinition, ...] = ()
    ) -> tuple[AllowedContract, object]:
        if issubclass(contract, ConflictResolution):
            raise UnsafeContractError("LLM output cannot create a ConflictResolution; operator confirmation is required")
        return self._runner.run(task=task, model=model, prompt=prompt, contract=contract, tools=tools)
