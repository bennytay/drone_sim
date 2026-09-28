import pytest
from test_investigation import state

from drone_sim.investigation import ResultKind, TestResult
from drone_sim.investigation_assistant import (
    InvestigationGuidance,
    PlanningGapExplanation,
    VariableRangeProposal,
    propose_investigation_guidance,
)
from drone_sim.llm import LLMRequest, LLMResponse, StructuredOutputRunner


class Replay:
    def __init__(self, guidance: InvestigationGuidance) -> None:
        self.guidance = guidance

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=self.guidance.model_dump_json(),
        )


def test_guidance_is_typed_and_has_no_verdict_channel() -> None:
    coverage = state().coverage
    guidance = propose_investigation_guidance(
        runner=StructuredOutputRunner(
            Replay(
                InvestigationGuidance(
                    refinement_ranges=(
                        VariableRangeProposal(
                            deployment_path="/conditions/wind_speed_mps",
                            lower=4,
                            upper=9,
                            rationale="Future boundary search may refine forecast wind.",
                        ),
                    ),
                    gap_explanations=(
                        PlanningGapExplanation(
                            subject="site_geometry",
                            explanation="No provider emits a surveyed site geometry payload.",
                            actionable_next_step="Register a validated site-geometry adapter.",
                        ),
                    ),
                )
            )
        ),
        model="replay",
        coverage=coverage,
        result=TestResult(
            hypothesis_id="hyp_wind_margin",
            kind=ResultKind.INCONCLUSIVE,
            summary="Router gap.",
            fidelity=0,
            terminal=True,
        ),
        routing_summary=("gap site_geometry",),
    )

    assert guidance.refinement_ranges[0].deployment_path == "/conditions/wind_speed_mps"
    assert guidance.gap_explanations[0].subject == "site_geometry"


def test_guidance_rejects_invalid_refinement_range() -> None:
    with pytest.raises(ValueError, match="lower < upper"):
        VariableRangeProposal(
            deployment_path="/conditions/wind_speed_mps",
            lower=9,
            upper=4,
            rationale="invalid",
        )
