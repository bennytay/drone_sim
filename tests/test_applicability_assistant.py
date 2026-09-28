from pathlib import Path

import pytest

from drone_sim.applicability_assistant import (
    ApplicabilityProposal,
    ApplicabilityProposalBatch,
    ApplicabilityReview,
    approve_applicability_rules,
    propose_applicability_rules,
)
from drone_sim.context import ContextOrchestrator
from drone_sim.coverage import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Comparison,
    EvidencePredicate,
    assess_coverage,
    default_profiles,
)
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.ir import DeploymentIR
from drone_sim.llm import LLMRequest, LLMResponse, StructuredOutputRunner

EXAMPLES = Path(__file__).parents[1] / "examples"


class Replay:
    def __init__(self, value: ApplicabilityProposalBatch) -> None:
        self.value = value
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=self.value.model_dump_json(),
        )


def demo_deployment() -> DeploymentIR:
    return DeploymentIR.model_validate_json(
        (EXAMPLES / "demo_deployment.json").read_text()
    )


def proposed_rules(deployment: DeploymentIR) -> ApplicabilityProposalBatch:
    baseline = {profile.mechanism_id: profile for profile in default_profiles()}

    def rule(mechanism_id: str, ruled_out_by: EvidencePredicate, *, extra=()):
        return ApplicabilityRule(
            all_of=(*baseline[mechanism_id].applicability.all_of, *extra),
            ruled_out_by=(ruled_out_by,),
        )

    return ApplicabilityProposalBatch(
        taxonomy_version=DEFAULT_FAILURE_TAXONOMY.version,
        deployment_id=deployment.deployment_id,
        proposals=(
            ApplicabilityProposal(
                mechanism_id="environment_weather.wind.steady_limit",
                rule=rule(
                    "environment_weather.wind.steady_limit",
                    EvidencePredicate(
                        path="/conditions/wind_speed_mps",
                        comparison=Comparison.LTE,
                        value=deployment.vehicle.max_wind_speed_mps,
                        description="Observed steady wind is within the reviewed aircraft limit.",
                    ),
                ),
                rationale="The reviewed nominal forecast is below the approved steady-wind limit.",
            ),
            ApplicabilityProposal(
                mechanism_id="environment_weather.visibility.degradation",
                rule=rule(
                    "environment_weather.visibility.degradation",
                    EvidencePredicate(
                        path="/conditions/visibility_m",
                        comparison=Comparison.GTE,
                        value=5_000,
                        description="Reviewed visibility is adequate for the nominal flight window.",
                    ),
                ),
                rationale="The reviewed visibility observation is clear rather than degraded.",
            ),
            ApplicabilityProposal(
                mechanism_id="environment_weather.visibility.precipitation",
                rule=rule(
                    "environment_weather.visibility.precipitation",
                    EvidencePredicate(
                        path="/conditions/precipitation_mm_h",
                        comparison=Comparison.EQUALS,
                        value=0,
                        description="Reviewed weather reports no precipitation.",
                    ),
                    extra=(
                        EvidencePredicate(
                            path="/conditions/precipitation_mm_h",
                            comparison=Comparison.GTE,
                            value=0,
                            description="A precipitation observation is required before rule-out.",
                        ),
                    ),
                ),
                rationale="No precipitation is recorded for the reviewed nominal flight window.",
            ),
        ),
    )


def reviewed_profiles(deployment: DeploymentIR):
    replay = Replay(proposed_rules(deployment))
    batch = propose_applicability_rules(
        runner=StructuredOutputRunner(replay), model="replay", deployment=deployment
    )
    reviewed = approve_applicability_rules(
        batch,
        ApplicabilityReview(
            operator_id="demo-operator",
            confirmed=True,
            rationale="Reviewed against the planned nominal weather window.",
        ),
    )
    assert replay.requests[0].prompt.id == "applicability-rule-proposal"
    return reviewed


def test_proposal_only_targets_drone_taxonomy_leaf() -> None:
    with pytest.raises(ValueError, match="taxonomy leaf"):
        ApplicabilityProposal(
            mechanism_id="ground_robot.weather",
            rule=ApplicabilityRule(
                all_of=(EvidencePredicate(path="/conditions", description="weather"),)
            ),
            rationale="out of scope",
        )


def test_unreviewed_llm_proposals_cannot_change_deterministic_coverage() -> None:
    deployment = demo_deployment()
    batch = proposed_rules(deployment)

    with pytest.raises(PermissionError, match="explicit operator confirmation"):
        approve_applicability_rules(
            batch,
            ApplicabilityReview(
                operator_id="demo-operator",
                confirmed=False,
                rationale="Not yet reviewed.",
            ),
        )

    baseline = assess_coverage(deployment)
    assert (
        sum(
            entry.applicability == ApplicabilityStatus.RULED_OUT
            for entry in baseline.entries
        )
        == 0
    )


def test_reviewed_profiles_rule_out_nominal_weather_without_losing_expected_mechanisms() -> (
    None
):
    deployment = demo_deployment()
    reviewed = reviewed_profiles(deployment)
    coverage = assess_coverage(deployment, reviewed.profiles)
    statuses = {entry.mechanism_id: entry.applicability for entry in coverage.entries}

    assert reviewed.taxonomy_version == DEFAULT_FAILURE_TAXONOMY.version
    assert len(reviewed.profiles) == len(default_profiles())
    assert {
        mechanism_id
        for mechanism_id, status in statuses.items()
        if status == ApplicabilityStatus.RULED_OUT
    } >= {
        "environment_weather.wind.steady_limit",
        "environment_weather.visibility.degradation",
        "environment_weather.visibility.precipitation",
    }
    for mechanism_id in (
        "energy_battery.reserve.route_demand",
        "vehicle_operating_envelope.loading.mass",
        "geometry_clearance.route.static_obstacle",
    ):
        assert statuses[mechanism_id] == ApplicabilityStatus.APPLIES


def test_missing_review_evidence_stays_unknown_not_ruled_out() -> None:
    deployment = demo_deployment()
    missing_precipitation = deployment.model_copy(
        update={
            "conditions": deployment.conditions.model_copy(
                update={"precipitation_mm_h": None}
            )
        }
    )
    coverage = assess_coverage(
        missing_precipitation, reviewed_profiles(missing_precipitation).profiles
    )
    precipitation = next(
        entry
        for entry in coverage.entries
        if entry.mechanism_id == "environment_weather.visibility.precipitation"
    )

    assert precipitation.applicability == ApplicabilityStatus.UNKNOWN


@pytest.mark.parametrize(
    ("folder_name", "weather_present"),
    (
        ("01_rooftop-inspection_clean", True),
        ("02_solar-farm-survey_messy", True),
        ("05_bridge-inspection_split", False),
    ),
)
def test_reviewed_rules_discriminate_ready_synthetic_corpus(
    tmp_path: Path, folder_name: str, weather_present: bool
) -> None:
    root = EXAMPLES / "synthetic_deployments" / folder_name
    evidence, _ = ContextOrchestrator(
        root, tmp_path / f"{folder_name}.state.json"
    ).run()
    assert evidence is not None

    coverage = assess_coverage(
        evidence.deployment, reviewed_profiles(evidence.deployment).profiles
    )
    ruled_out = {
        entry.mechanism_id
        for entry in coverage.entries
        if entry.applicability == ApplicabilityStatus.RULED_OUT
    }

    weather_mechanisms = {
        "environment_weather.wind.steady_limit",
        "environment_weather.visibility.degradation",
        "environment_weather.visibility.precipitation",
    }
    if weather_present:
        assert weather_mechanisms <= ruled_out
    else:
        statuses = {
            entry.mechanism_id: entry.applicability for entry in coverage.entries
        }
        assert all(
            statuses[mechanism_id] == ApplicabilityStatus.UNKNOWN
            for mechanism_id in weather_mechanisms
        )
