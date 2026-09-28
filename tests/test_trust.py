import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from drone_sim.graph import EvaluationGoal
from drone_sim.ir import ArtifactRef
from drone_sim.provenance import ConfidenceLevel
from drone_sim.reference_tools import MomentumEnergy
from drone_sim.registry import (
    Interval,
    OperatingContext,
    Region,
    RuntimeSpec,
    ToolManifest,
)
from drone_sim.routing import BoundaryStatus, Decision, FidelityRouter
from drone_sim.trust import (
    FeedbackPoint,
    ModelTrustRecord,
    ResidualStats,
    TrustLedger,
    TrustLevel,
    TrustScope,
    ValidationDataset,
)

from test_graph import CALM, reserve_hypothesis, toolbox
from test_routing import INITIAL, PhysicsEnergy, threshold

MANIFESTS = Path(__file__).parents[1] / "examples" / "tool_manifests"
ENERGY = MomentumEnergy.manifest
PINNED = ArtifactRef(id="bench", uri="validation/bench.parquet", role="telemetry", sha256="c" * 64)
WIND_0_10 = Region(
    bounds=(Interval(variable="wind_speed_mps", minimum=0, maximum=10, unit="m/s"),)
)


def residuals(measure: str, count: int, spread: float = 0.05) -> ResidualStats:
    stats = ResidualStats(measure=measure)
    for index in range(count):
        stats = stats.add(spread if index % 2 else -spread)
    return stats


def validated(manifest: ToolManifest, measure: str = "remaining_energy_wh", **extra) -> ModelTrustRecord:
    return ModelTrustRecord(
        model_id=manifest.id,
        version=manifest.version,
        datasets=(
            ValidationDataset(
                id="bench-2026",
                description="Bench and flight power logs",
                region=WIND_0_10,
                sample_count=64,
                artifact=PINNED,
                verified=True,
            ),
        ),
        residuals=(residuals(measure, 40),),
        **extra,
    )


def at(wind: float) -> OperatingContext:
    return OperatingContext(airframe="multirotor", variables={"wind_speed_mps": wind})


def test_verified_validation_supports_high_confidence() -> None:
    ledger = TrustLedger()
    ledger.record(validated(ENERGY))

    assessment = ledger.assess(ENERGY, at(6), measure="remaining_energy_wh")

    assert assessment.level == TrustLevel.VALIDATED
    assert assessment.max_confidence == ConfidenceLevel.HIGH
    assert assessment.datasets == ("bench-2026",)
    assert 0.1 < assessment.error_bound < 0.2
    assert "validated here" in assessment.report_note()


def test_findings_outside_validated_region_are_capped_and_explained() -> None:
    ledger = TrustLedger()
    ledger.record(validated(ENERGY))

    assessment = ledger.assess(ENERGY, at(11.5), measure="remaining_energy_wh")

    assert assessment.level == TrustLevel.EXTRAPOLATED
    assert assessment.max_confidence == ConfidenceLevel.LOW
    assert "outside validated region: wind_speed_mps" in assessment.report_note()


def test_unsupported_regions_and_invalid_points_cannot_support_findings() -> None:
    ledger = TrustLedger()
    icing = Region(bounds=(Interval(variable="temperature_c", maximum=0, unit="C"),))
    ledger.record(validated(ENERGY, unsupported=(icing,)))
    cold = OperatingContext(
        airframe="multirotor", variables={"wind_speed_mps": 4, "temperature_c": -5}
    )

    assert not ledger.assess(ENERGY, cold).usable_for_findings
    assert ledger.assess(ENERGY, at(20)).level == TrustLevel.UNSUPPORTED


def test_trust_is_version_specific() -> None:
    ledger = TrustLedger()
    ledger.record(validated(ENERGY))
    upgraded = ENERGY.model_copy(update={"version": "0.2.0"})

    assessment = ledger.assess(upgraded, at(6))

    assert assessment.level == TrustLevel.UNVALIDATED
    assert "evidence exists for builtin.momentum-energy@0.1.0" in assessment.reasons[0]


def test_scoped_evidence_applies_only_to_its_customer() -> None:
    ledger = TrustLedger()
    acme = TrustScope(kind="customer", identifier="acme")
    record = validated(ENERGY)
    record = record.model_copy(
        update={"datasets": tuple(d.model_copy(update={"scope": acme}) for d in record.datasets)}
    )
    ledger.record(record)

    own = ledger.assess(ENERGY, at(6), TrustScope(kind="deployment", identifier="acme/roof-1"))
    other = ledger.assess(ENERGY, at(6), TrustScope(kind="deployment", identifier="zeta/pier"))

    assert own.level == TrustLevel.VALIDATED
    assert other.level == TrustLevel.EXTRAPOLATED


def test_unverified_attestations_cap_confidence() -> None:
    manifest = ToolManifest.model_validate(
        json.loads((MANIFESTS / "empirical_wind_envelope.json").read_text())
    )
    ledger = TrustLedger()
    ledger.seed_from_manifest(manifest)
    context = OperatingContext(
        airframe="multirotor", variables={"wind_speed_mps": 6, "temperature_c": 20}
    )

    assessment = ledger.assess(manifest, context)

    assert assessment.level == TrustLevel.VALIDATED
    assert assessment.max_confidence == ConfidenceLevel.MEDIUM
    assert "only unverified attestations" in assessment.reasons[0]


def test_verified_datasets_must_be_pinned() -> None:
    with pytest.raises(ValidationError, match="pinned artifact"):
        ValidationDataset(
            id="x", description="unpinned", region=WIND_0_10, sample_count=3, verified=True
        )


def test_deployment_feedback_grows_trust_regions_and_detects_drift() -> None:
    ledger = TrustLedger()
    scope = TrustScope(kind="customer", identifier="acme")
    key = ENERGY.key

    def feed(wind: float, residual: float) -> ModelTrustRecord:
        return ledger.record_outcome(
            key,
            FeedbackPoint(
                measure="remaining_energy_wh",
                predicted=50.0,
                observed=50.0 + residual,
                context=at(wind),
                scope=scope,
                source="flight-log",
            ),
        )

    for index in range(10):
        feed(3 + index * 0.5, 0.1 if index % 2 else -0.1)
    deployment = TrustScope(kind="deployment", identifier="acme/roof-1")
    grown = ledger.assess(ENERGY, at(5), deployment, "remaining_energy_wh")
    assert grown.level == TrustLevel.VALIDATED
    assert grown.max_confidence == ConfidenceLevel.MEDIUM
    assert ledger.assess(ENERGY, at(9), deployment).level == TrustLevel.EXTRAPOLATED

    record = feed(5, 3.0)
    assert record.drift_measures == ("remaining_energy_wh",)
    drifted = ledger.assess(ENERGY, at(5), deployment, "remaining_energy_wh")
    assert any("drift" in reason for reason in drifted.reasons)


class QuickEnergy(MomentumEnergy):
    manifest = MomentumEnergy.manifest.model_copy(
        update={
            "id": "stub.energy-quick",
            "runtime": RuntimeSpec(typical_runtime_s=0.001),
        }
    )


GOAL = EvaluationGoal.for_hypothesis(reserve_hypothesis())


def test_selection_prefers_validated_models_over_capability_match() -> None:
    registry, tools = toolbox(QuickEnergy())
    ledger = TrustLedger()
    ledger.record(validated(ENERGY))

    untrusting = FidelityRouter(registry, tools).investigate(GOAL, CALM, threshold(50), INITIAL)
    trusting = FidelityRouter(registry, tools, trust=ledger).investigate(
        GOAL, CALM, threshold(50), INITIAL
    )

    assert untrusting.steps[0].providers["energy.route_demand"] == "stub.energy-quick@0.1.0"
    first = trusting.steps[0]
    assert first.providers["energy.route_demand"] == "builtin.momentum-energy@0.1.0"
    choice = next(s for s in first.selection if s.startswith("energy.route_demand"))
    assert "preferred over less-trusted stub.energy-quick@0.1.0" in choice


def test_untrusted_result_escalates_to_a_validated_model() -> None:
    registry, tools = toolbox(PhysicsEnergy())
    ledger = TrustLedger()
    ledger.record(validated(PhysicsEnergy.manifest))

    outcome = FidelityRouter(registry, tools, trust=ledger).investigate(
        GOAL, CALM, threshold(50), INITIAL
    )

    first = outcome.steps[0].assessments[0]
    assert first.status == BoundaryStatus.UNTRUSTED
    assert "no validation evidence" in first.reason
    assert outcome.final.providers["energy.route_demand"] == "stub.energy-physics@1.0.0"
    assert outcome.final.assessments[0].trust == TrustLevel.VALIDATED
    assert outcome.final.assessments[0].max_confidence == ConfidenceLevel.HIGH
    assert outcome.final.decision == Decision.ACCEPT


def test_empirical_residuals_widen_optimistic_declared_errors() -> None:
    registry, tools = toolbox(PhysicsEnergy())
    ledger = TrustLedger()
    noisy = validated(PhysicsEnergy.manifest).model_copy(
        update={"residuals": (residuals("remaining_energy_wh", 40, spread=0.4),)}
    )
    ledger.record(noisy)
    ledger.record(validated(ENERGY))

    outcome = FidelityRouter(registry, tools, trust=ledger).investigate(
        GOAL, CALM, threshold(0.3), INITIAL
    )

    physics = outcome.final.assessments[0]
    assert physics.provider_key == "stub.energy-physics@1.0.0"
    assert physics.status == BoundaryStatus.NEAR_BOUNDARY
    assert physics.error > 0.02
    assert outcome.final.decision == Decision.EXHAUSTED
