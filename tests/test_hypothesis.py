import pytest
from pydantic import ValidationError

from drone_sim.hypothesis import (
    FailureHypothesis,
    HypothesisGenerationContract,
    HypothesisUncertainty,
    HypothesisVariable,
    ObservationCondition,
    SupportingReference,
    SupportKind,
    merge_duplicates,
)


def hypothesis(identifier: str = "hyp_wind_margin") -> FailureHypothesis:
    return FailureHypothesis(
        id=identifier,
        mechanism_id="environment_weather.wind.steady_limit",
        affected_target="wind-limit constraint",
        variables=(
            HypothesisVariable(
                name="wind_speed_mps",
                deployment_path="/conditions/wind_speed_mps",
                role="cause",
            ),
        ),
        causal_path=(
            "Route-local wind rises.",
            "Control demand consumes margin.",
            "The constraint may be breached.",
        ),
        supporting_references=(
            SupportingReference(
                kind=SupportKind.DEPLOYMENT_EVIDENCE,
                reference_id="fact-wind",
                summary="Forecast and vehicle limit are available.",
            ),
            SupportingReference(
                kind=SupportKind.TAXONOMY,
                reference_id="environment_weather.wind.steady_limit",
                summary="Catalog mechanism.",
            ),
        ),
        uncertainty=HypothesisUncertainty.MEDIUM,
        uncertainty_reason="Forecast is not route-local measurement.",
        materiality="high",
        candidate_testabilities=("analytical", "simulation"),
        confirm_if=(
            ObservationCondition(
                observable="control_saturation",
                description="A judge observes loss of control margin.",
            ),
        ),
        falsify_if=(
            ObservationCondition(
                observable="control_saturation",
                description="A judge observes adequate control margin over the declared range.",
            ),
        ),
    )


def test_hypothesis_is_falsifiable_and_planner_ready() -> None:
    value = hypothesis()
    assert value.duplicate_key[0] == "environment_weather.wind.steady_limit"
    assert value.confirm_if and value.falsify_if


def test_hypothesis_requires_deployment_evidence() -> None:
    data = hypothesis().model_dump()
    data["supporting_references"] = [data["supporting_references"][1]]
    with pytest.raises(ValidationError, match="deployment evidence"):
        FailureHypothesis.model_validate(data)


def test_contract_rejects_unmerged_duplicates() -> None:
    with pytest.raises(ValidationError, match="merged explicitly"):
        HypothesisGenerationContract(
            hypotheses=(hypothesis(), hypothesis("hyp_wind_margin_2"))
        )


def test_duplicate_merge_preserves_the_noncanonical_proposal() -> None:
    original = HypothesisGenerationContract.model_construct(
        hypotheses=(hypothesis(), hypothesis("hyp_wind_margin_2"))
    )
    merged = merge_duplicates(original)
    assert merged.hypotheses[1].merged_into == "hyp_wind_margin"
