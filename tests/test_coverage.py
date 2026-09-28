import json
from pathlib import Path

import pytest

from drone_sim.coverage import (
    ApplicabilityStatus,
    CoverageState,
    EvidencePredicate,
    assess_coverage,
    default_profiles,
)
from drone_sim.ir import DeploymentIR

FIXTURE = Path(__file__).parents[1] / "examples" / "demo_deployment.json"


def deployment() -> DeploymentIR:
    return DeploymentIR.model_validate(json.loads(FIXTURE.read_text()))


def test_coverage_map_accounts_for_every_taxonomy_leaf() -> None:
    coverage = assess_coverage(deployment())

    assert len(coverage.entries) == len(default_profiles())
    assert coverage.residual_unknowns[0].id == "taxonomy_gap"
    assert any(entry.state == CoverageState.UNEXAMINED for entry in coverage.entries)
    assert any(entry.state == CoverageState.UNCERTAIN for entry in coverage.entries)


def test_missing_context_is_uncertain_not_ruled_out() -> None:
    coverage = assess_coverage(deployment())
    wind = next(
        entry
        for entry in coverage.entries
        if entry.mechanism_id
        == "deployment_external_actors.dynamic_site.temporary_obstacle"
    )

    assert wind.applicability == ApplicabilityStatus.UNKNOWN
    assert wind.state == CoverageState.UNCERTAIN


def test_coverage_records_completed_deterministic_test() -> None:
    coverage = assess_coverage(deployment())
    target = next(
        entry
        for entry in coverage.entries
        if entry.applicability == ApplicabilityStatus.APPLIES
    )

    recorded = coverage.record(
        target.mechanism_id, CoverageState.TESTED, "Geometry judge v1 passed."
    )

    assert (
        next(
            entry
            for entry in recorded.entries
            if entry.mechanism_id == target.mechanism_id
        ).state
        == CoverageState.TESTED
    )


def test_non_applicable_or_unknown_mechanisms_cannot_be_marked_tested() -> None:
    coverage = assess_coverage(deployment())
    target = next(
        entry
        for entry in coverage.entries
        if entry.applicability != ApplicabilityStatus.APPLIES
    )

    with pytest.raises(ValueError, match="only applicable"):
        coverage.record(target.mechanism_id, CoverageState.TESTED, "Not permitted")


def test_predicate_requires_a_value_when_comparing() -> None:
    with pytest.raises(ValueError, match="require a value"):
        EvidencePredicate(
            path="/conditions/wind_speed_mps", comparison="gt", description="Wind"
        )


def test_profiles_cover_taxonomy_exactly_once() -> None:
    profiles = default_profiles()
    assert len({profile.mechanism_id for profile in profiles}) == len(profiles)
