from drone_sim.hypothesis_generator import generate_hypotheses
from drone_sim.llm import LLMMessage, LLMResponse, MessageRole, Prompt, StructuredOutputRunner
from test_hypothesis import hypothesis

class Replay:
    def complete(self, request):  # type: ignore[no-untyped-def]
        return LLMResponse(model=request.model, prompt_id=request.prompt.id, prompt_version=request.prompt.version, text='{"hypotheses": [' + hypothesis().model_dump_json() + ']}')

def test_replay_generator_returns_existing_hypothesis_contract() -> None:
    generated = generate_hypotheses(runner=StructuredOutputRunner(Replay()), model="replay", prompt=Prompt(id="hyp", version="1", messages=(LLMMessage(role=MessageRole.USER, content="propose"),)))
    assert generated.hypotheses[0].mechanism_id == "environment_weather.wind.steady_limit"
