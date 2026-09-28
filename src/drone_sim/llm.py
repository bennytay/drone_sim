"""Provider-neutral, contract-validated LLM calls for drone verification.

This module deliberately does not decide any readiness outcome.  It is an
edge adapter: callers supply a versioned prompt and an existing Pydantic
contract, while deterministic code validates the returned data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class LLMError(RuntimeError):
    """Base error for an LLM edge failure."""


class LLMUnavailableError(LLMError):
    """Raised before a hosted request when the provider is not configured."""


class StructuredOutputError(LLMError):
    """Raised after all bounded repair attempts fail validation."""

    def __init__(self, contract_name: str, validation_errors: tuple[str, ...]):
        self.contract_name = contract_name
        self.validation_errors = validation_errors
        super().__init__(
            f"LLM output could not satisfy {contract_name} after bounded repairs: "
            + "; ".join(validation_errors)
        )


class LLMTask(StrEnum):
    EXTRACTION = "extraction"
    HYPOTHESIS_REASONING = "hypothesis_reasoning"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str = Field(min_length=1)


class Prompt(BaseModel):
    """A versioned prompt whose identity is persisted with downstream output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    messages: tuple[LLMMessage, ...] = Field(min_length=1)


class ToolDefinition(BaseModel):
    """A provider-neutral declaration of a deterministic function an agent may call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: LLMTask
    model: str = Field(min_length=1)
    prompt: Prompt
    tools: tuple[ToolDefinition, ...] = ()


class LLMResponse(BaseModel):
    """Normalized hosted response, including enough identity for a future ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    provider_request_id: str | None = None


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    extraction_model: str = "claude-haiku-4-5"
    hypothesis_model: str = "claude-sonnet-4-5"
    timeout_s: float = 30.0
    retries: int = 2

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMUnavailableError(
                "LLM is not configured: set ANTHROPIC_API_KEY to enable hosted calls"
            )
        try:
            timeout_s = float(os.environ.get("DRONE_SIM_LLM_TIMEOUT_S", "30"))
            retries = int(os.environ.get("DRONE_SIM_LLM_RETRIES", "2"))
        except ValueError as error:
            raise LLMUnavailableError("LLM timeout and retries must be numeric") from error
        if timeout_s <= 0 or retries < 0:
            raise LLMUnavailableError("LLM timeout must be positive and retries non-negative")
        return cls(
            api_key=api_key,
            extraction_model=os.environ.get(
                "DRONE_SIM_LLM_EXTRACTION_MODEL", "claude-haiku-4-5"
            ),
            hypothesis_model=os.environ.get(
                "DRONE_SIM_LLM_HYPOTHESIS_MODEL", "claude-sonnet-4-5"
            ),
            timeout_s=timeout_s,
            retries=retries,
        )

    def model_for(self, task: LLMTask) -> str:
        return (
            self.extraction_model
            if task == LLMTask.EXTRACTION
            else self.hypothesis_model
        )


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class AnthropicProvider:
    """Minimal Anthropic Messages API adapter with no SDK dependency.

    The protocol remains local and testable; this adapter only serializes the
    explicit request and never turns model text into product facts itself.
    """

    endpoint = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(self, config: LLMConfig):
        self._config = config

    def complete(self, request: LLMRequest) -> LLMResponse:
        system = "\n\n".join(
            message.content for message in request.prompt.messages if message.role == MessageRole.SYSTEM
        )
        messages = [
            {"role": message.role.value, "content": message.content}
            for message in request.prompt.messages
            if message.role != MessageRole.SYSTEM
        ]
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if request.tools:
            body["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in request.tools
            ]
        encoded = json.dumps(body).encode("utf-8")
        last_error: Exception | None = None
        for _attempt in range(self._config.retries + 1):
            try:
                http_request = Request(
                    self.endpoint,
                    data=encoded,
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self._config.api_key,
                        "anthropic-version": self.api_version,
                    },
                    method="POST",
                )
                with urlopen(http_request, timeout=self._config.timeout_s) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return self._parse_response(request, payload)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
        raise LLMError(f"Anthropic request failed after {self._config.retries + 1} attempt(s): {last_error}")

    @staticmethod
    def _parse_response(request: LLMRequest, payload: dict[str, Any]) -> LLMResponse:
        text = "\n".join(
            block["text"] for block in payload.get("content", []) if block.get("type") == "text"
        )
        tool_calls = tuple(
            ToolCall(id=block["id"], name=block["name"], arguments=block["input"])
            for block in payload.get("content", [])
            if block.get("type") == "tool_use"
        )
        return LLMResponse(
            model=payload.get("model", request.model),
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=text,
            tool_calls=tool_calls,
            provider_request_id=payload.get("id"),
        )


Contract = TypeVar("Contract", bound=BaseModel)


class StructuredOutputRunner:
    """Validate JSON against an existing contract, repairing at most N times."""

    def __init__(self, provider: LLMProvider, *, max_repairs: int = 2):
        if max_repairs < 0:
            raise ValueError("max_repairs must be non-negative")
        self._provider = provider
        self._max_repairs = max_repairs

    def run(
        self, *, task: LLMTask, model: str, prompt: Prompt, contract: type[Contract], tools: tuple[ToolDefinition, ...] = ()
    ) -> tuple[Contract, LLMResponse]:
        request = LLMRequest(task=task, model=model, prompt=prompt, tools=tools)
        errors: tuple[str, ...] = ()
        for attempt in range(self._max_repairs + 1):
            response = self._provider.complete(request)
            try:
                return contract.model_validate_json(response.text), response
            except (ValidationError, ValueError) as error:
                errors = tuple(item["msg"] for item in getattr(error, "errors", lambda: [])()) or (str(error),)
                if attempt == self._max_repairs:
                    break
                request = request.model_copy(
                    update={
                        "prompt": Prompt(
                            id=prompt.id,
                            version=prompt.version,
                            messages=(
                                *prompt.messages,
                                LLMMessage(role=MessageRole.ASSISTANT, content=response.text or "<no text returned>"),
                                LLMMessage(
                                    role=MessageRole.USER,
                                    content=(
                                        "Repair the previous response. Return only valid JSON for the requested contract. "
                                        "Validation errors: " + "; ".join(errors)
                                    ),
                                ),
                            ),
                        )
                    }
                )
        raise StructuredOutputError(contract.__name__, errors)
