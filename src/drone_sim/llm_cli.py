"""Live smoke command for the configured hosted LLM provider."""

import sys

from drone_sim.llm import (
    AnthropicProvider,
    LLMConfig,
    LLMMessage,
    LLMRequest,
    LLMTask,
    LLMUnavailableError,
    MessageRole,
    Prompt,
)


def main() -> int:
    try:
        config = LLMConfig.from_env()
    except LLMUnavailableError as error:
        print(f"LLM unavailable: {error}", file=sys.stderr)
        return 2
    response = AnthropicProvider(config).complete(
        LLMRequest(
            task=LLMTask.EXTRACTION,
            model=config.model_for(LLMTask.EXTRACTION),
            prompt=Prompt(
                id="llm_smoke", version="0.1.0",
                messages=(LLMMessage(role=MessageRole.USER, content="Reply with exactly: ok"),),
            ),
        )
    )
    print(f"model={response.model} request_id={response.provider_request_id} response={response.text}")
    return 0
