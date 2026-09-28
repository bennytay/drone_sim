"""Persistent, replayable audit ledger for hosted LLM calls.

The ledger stores request fingerprints and explicit input references rather
than duplicating deployment bytes. It is deliberately independent of provider
and contract choices so it can audit every edge call.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.llm import LLMError, LLMProvider, LLMRequest, LLMResponse


class LedgerMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class BudgetExceededError(LLMError):
    """A declared call, token, or cost budget stopped the agent explicitly."""


class ReplayMissError(LLMError):
    """A replay run cannot silently substitute a live hosted request."""


class InputReference(BaseModel):
    """Audit identity of an input without retaining its customer content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelPrice(BaseModel):
    """Pinned USD prices per million tokens for one named model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million_usd: float = Field(ge=0)
    output_per_million_usd: float = Field(ge=0)


class LLMBudget(BaseModel):
    """Per-ledger-run budget, optionally narrowed for one named stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_id: str
    prompt_version: str
    model: str
    stage: str
    mode: LedgerMode
    input_references: tuple[InputReference, ...] = ()
    context_trace_indices: tuple[int, ...] = ()
    response: LLMResponse
    usage: TokenUsage = TokenUsage()
    latency_ms: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    validation_outcome: str = "unvalidated"
    validation_errors: tuple[str, ...] = ()
    recorded_at: datetime


class LedgerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_version: str = "0.1.0"
    entries: list[LedgerEntry] = Field(default_factory=list)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def prompt_hash(request: LLMRequest) -> str:
    return _sha256(request.prompt.model_dump(mode="json"))


def request_hash(
    request: LLMRequest,
    *,
    stage: str,
    input_references: tuple[InputReference, ...],
    context_trace_indices: tuple[int, ...],
) -> str:
    """Fingerprint all response-affecting fields without persisting their bytes."""

    return _sha256(
        {
            "request": request.model_dump(mode="json"),
            "stage": stage,
            "input_references": [reference.model_dump(mode="json") for reference in input_references],
            "context_trace_indices": context_trace_indices,
        }
    )


class CallLedger:
    """Atomically persisted ledger, intended to live beside workflow state."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self._state = self._load()

    def _load(self) -> LedgerState:
        if not self.path.exists():
            return LedgerState()
        return LedgerState.model_validate_json(self.path.read_text())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(self._state.model_dump_json(indent=2))
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get_recording(self, value: str) -> LedgerEntry | None:
        """Latest recording for a deterministic request fingerprint."""
        return next(
            (entry for entry in reversed(self._state.entries) if entry.request_hash == value),
            None,
        )

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._state.entries)

    def record(self, entry: LedgerEntry) -> None:
        self._state.entries.append(entry)
        self.save()

    def mark_validation(self, value: str, *, valid: bool, errors: tuple[str, ...] = ()) -> None:
        for index, entry in enumerate(self._state.entries):
            if entry.id == value:
                self._state.entries[index] = entry.model_copy(
                    update={"validation_outcome": "valid" if valid else "invalid", "validation_errors": errors}
                )
                break
        else:
            raise KeyError(f"unknown ledger entry {value}")
        self.save()


class LedgeredProvider:
    """Provider wrapper that enforces budgets and records live or replay calls."""

    def __init__(
        self,
        provider: LLMProvider | None,
        ledger: CallLedger,
        *,
        mode: LedgerMode,
        stage: str,
        budget: LLMBudget = LLMBudget(),
        model_prices: dict[str, ModelPrice] | None = None,
        input_references: tuple[InputReference, ...] = (),
        context_trace_indices: tuple[int, ...] = (),
    ):
        self._provider = provider
        self.ledger = ledger
        self.mode = mode
        self.stage = stage
        self.budget = budget
        self.model_prices = model_prices or {}
        self.input_references = input_references
        self.context_trace_indices = context_trace_indices
        self.last_entry_id: str | None = None

    def _stage_entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(entry for entry in self.ledger.entries() if entry.stage == self.stage)

    def _check_budget(self) -> None:
        entries = self._stage_entries()
        calls = len(entries)
        tokens = sum(entry.usage.total_tokens for entry in entries)
        cost = sum(entry.cost_usd for entry in entries)
        if self.budget.max_calls is not None and calls >= self.budget.max_calls:
            raise BudgetExceededError(f"LLM budget stopped stage {self.stage}: call count {calls} reached limit")
        if self.budget.max_tokens is not None and tokens >= self.budget.max_tokens:
            raise BudgetExceededError(f"LLM budget stopped stage {self.stage}: token count {tokens} reached limit")
        if self.budget.max_cost_usd is not None and cost >= self.budget.max_cost_usd:
            raise BudgetExceededError(f"LLM budget stopped stage {self.stage}: cost ${cost:.6f} reached limit")

    def complete(self, request: LLMRequest) -> LLMResponse:
        value = request_hash(request, stage=self.stage, input_references=self.input_references, context_trace_indices=self.context_trace_indices)
        existing = self.ledger.get_recording(value)
        if self.mode == LedgerMode.REPLAY:
            if existing is None:
                raise ReplayMissError(f"No recorded LLM response for request hash {value}")
            self._check_budget()
            replay_entry = LedgerEntry(
                id=str(uuid.uuid4()), request_hash=value, prompt_hash=prompt_hash(request),
                prompt_id=request.prompt.id, prompt_version=request.prompt.version,
                model=existing.response.model, stage=self.stage, mode=LedgerMode.REPLAY,
                input_references=self.input_references, context_trace_indices=self.context_trace_indices,
                response=existing.response, usage=existing.usage, latency_ms=0, cost_usd=0,
                recorded_at=datetime.now(tz=UTC),
            )
            self.ledger.record(replay_entry)
            self.last_entry_id = replay_entry.id
            return existing.response
        self._check_budget()
        if self._provider is None:
            raise LLMError("A live ledgered provider requires a hosted provider")
        started = datetime.now(tz=UTC)
        response = self._provider.complete(request)
        latency_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
        usage = TokenUsage(input_tokens=response.input_tokens, output_tokens=response.output_tokens)
        price = self.model_prices.get(response.model)
        cost = 0.0 if price is None else (
            usage.input_tokens * price.input_per_million_usd + usage.output_tokens * price.output_per_million_usd
        ) / 1_000_000
        entry = LedgerEntry(
            id=str(uuid.uuid4()), request_hash=value, prompt_hash=prompt_hash(request), prompt_id=request.prompt.id,
            prompt_version=request.prompt.version, model=response.model, stage=self.stage, mode=self.mode,
            input_references=self.input_references, context_trace_indices=self.context_trace_indices,
            response=response, usage=usage, latency_ms=latency_ms, cost_usd=cost, recorded_at=started,
        )
        self.ledger.record(entry)
        self.last_entry_id = entry.id
        return response
