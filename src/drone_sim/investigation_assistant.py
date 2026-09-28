"""Typed LLM guidance at the edge of the deterministic investigation loop."""

from __future__ import annotations

import json

from pydantic import Field, model_validator

from drone_sim.coverage import CoverageMap
from drone_sim.hypothesis import FailureHypothesis, HypothesisStatus
from drone_sim.investigation import TestResult
from drone_sim.ir import StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)


class VariableRangeProposal(StrictModel):
    """A candidate range for future boundary search, not an executable test."""

    deployment_path: str = Field(pattern=r"^/")
    lower: float
    upper: float
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> VariableRangeProposal:
        if self.lower >= self.upper:
            raise ValueError("refinement ranges require lower < upper")
        return self


class PlanningGapExplanation(StrictModel):
    subject: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    actionable_next_step: str = Field(min_length=1)


class InvestigationGuidance(StrictModel):
    """Untrusted proposals that may inform later follow-up work only."""

    contract_version: str = "0.1.0"
    follow_up_hypotheses: tuple[FailureHypothesis, ...] = ()
    refinement_ranges: tuple[VariableRangeProposal, ...] = ()
    gap_explanations: tuple[PlanningGapExplanation, ...] = ()

    @model_validator(mode="after")
    def proposals_cannot_claim_results(self) -> InvestigationGuidance:
        if any(
            proposal.status != HypothesisStatus.PROPOSED
            for proposal in self.follow_up_hypotheses
        ):
            raise ValueError("follow-up hypotheses must remain proposed")
        return self


def propose_investigation_guidance(
    *,
    runner: StructuredOutputRunner,
    model: str,
    coverage: CoverageMap,
    result: TestResult,
    routing_summary: tuple[str, ...],
) -> InvestigationGuidance:
    """Request validated follow-up/gap/range suggestions without a verdict channel."""

    guidance, _ = runner.run(
        task=LLMTask.HYPOTHESIS_REASONING,
        model=model,
        prompt=Prompt(
            id="investigation-guidance",
            version="1",
            messages=(
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Propose only follow-up drone hypotheses, future boundary-search "
                        "ranges, and actionable planning-gap explanations. Do not decide "
                        "pass/fail, alter the supplied result, or write simulator code."
                    ),
                ),
                LLMMessage(
                    role=MessageRole.USER,
                    content=json.dumps(
                        {
                            "coverage": coverage.model_dump(mode="json"),
                            "deterministic_result": result.model_dump(mode="json"),
                            "routing_summary": routing_summary,
                            "output_schema": InvestigationGuidance.model_json_schema(),
                        },
                        sort_keys=True,
                    ),
                ),
            ),
        ),
        contract=InvestigationGuidance,
    )
    return guidance
