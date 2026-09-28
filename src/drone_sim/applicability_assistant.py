"""Typed LLM proposals for applicability rules; evaluation stays deterministic."""
from drone_sim.coverage import ApplicabilityRule
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.ir import StrictModel
from pydantic import Field, model_validator
class ApplicabilityProposal(StrictModel):
    mechanism_id: str
    rule: ApplicabilityRule
    rationale: str = Field(min_length=1)
    @model_validator(mode="after")
    def leaf_only(self) -> "ApplicabilityProposal":
        if self.mechanism_id not in {leaf.id for leaf in DEFAULT_FAILURE_TAXONOMY.leaves()}:
            raise ValueError("applicability proposal must target a taxonomy leaf")
        return self
