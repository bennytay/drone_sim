"""Contract-validated agentic hypothesis generation; no verdicts or thresholds."""
from __future__ import annotations
from drone_sim.hypothesis import HypothesisGenerationContract, merge_duplicates
from drone_sim.llm import LLMTask, Prompt, StructuredOutputRunner

def generate_hypotheses(*, runner: StructuredOutputRunner, model: str, prompt: Prompt) -> HypothesisGenerationContract:
    contract, _ = runner.run(task=LLMTask.HYPOTHESIS_REASONING, model=model, prompt=prompt, contract=HypothesisGenerationContract)
    return merge_duplicates(contract)
