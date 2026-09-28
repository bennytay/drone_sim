from drone_sim.capabilities import DEFAULT_CAPABILITY_ONTOLOGY, DataKind
from drone_sim.graph import EvaluationGoal
from drone_sim.reference_tools import MomentumEnergy
from drone_sim.registry import (
    CapabilityProvision,
    CostClass,
    ErrorSpec,
    ExecutionMode,
    FidelityClass,
    OperatingContext,
    Reproducibility,
    RuntimeSpec,
    ToolManifest,
    UncertaintyKind,
)
from drone_sim.routing import (
    BoundaryStatus,
    Comparator,
    Decision,
    DecisionThreshold,
    FidelityRouter,
    RoutingPolicy,
)

from test_graph import CALM, ClosedLoopStub, reserve_hypothesis, toolbox
from test_interfaces import demo_deployment


class PhysicsEnergy(MomentumEnergy):
    """Stands in for a higher-fidelity energy model with tighter error."""

    def __init__(self, scale: float = 1.0):
        self.scale = scale

    manifest = ToolManifest(
        id="stub.energy-physics",
        version="1.0.0",
        name="Blade-element energy stub",
        description="Higher-fidelity stand-in with a 3 percent declared error.",
        provides=(CapabilityProvision(capability_id="energy.route_demand"),),
        airframes=("multirotor",),
        fidelity=FidelityClass.PHYSICS,
        errors=(
            ErrorSpec(
                measure="remaining_energy_wh",
                kind=UncertaintyKind.ABSOLUTE_BOUND,
                value=0.02,
                unit="Wh",
                basis="Validated against bench power logs",
            ),
        ),
        runtime=RuntimeSpec(typical_runtime_s=30),
        cost=CostClass.MEDIUM,
        execution_mode=ExecutionMode.LOCAL_PROCESS,
        reproducibility=Reproducibility(deterministic=True),
    )

    def compute(self, capability_id, inputs):
        outputs = dict(super().compute(capability_id, inputs))
        battery = outputs["battery_state"]
        consumed = battery.consumed_energy_wh * self.scale
        battery = battery.model_copy(update={"consumed_energy_wh": consumed})
        outputs["battery_state"] = battery
        outputs["measures"] = outputs["measures"].model_copy(
            update={
                "measures": tuple(
                    measure.model_copy(
                        update={
                            "value": {
                                "route_energy_wh": consumed,
                                "remaining_energy_wh": battery.remaining_energy_wh,
                            }.get(measure.name, measure.value),
                            "error": None,
                        }
                    )
                    for measure in outputs["measures"].measures
                )
            }
        )
        return outputs


GOAL = EvaluationGoal.for_hypothesis(reserve_hypothesis())
INITIAL = {DataKind.DEPLOYMENT: demo_deployment()}


def analytical_remaining() -> float:
    registry, tools = toolbox()
    outcome = FidelityRouter(registry, tools).investigate(
        GOAL,
        CALM,
        (DecisionThreshold(measure="remaining_energy_wh", comparator=Comparator.GTE, value=0),),
        INITIAL,
    )
    return outcome.final.record.measure("remaining_energy_wh").value


def threshold(offset: float) -> tuple[DecisionThreshold, ...]:
    return (
        DecisionThreshold(
            measure="remaining_energy_wh",
            comparator=Comparator.GTE,
            value=analytical_remaining() - offset,
            unit="Wh",
        ),
    )


def test_clear_margin_is_accepted_at_the_cheapest_fidelity() -> None:
    registry, tools = toolbox(PhysicsEnergy())

    outcome = FidelityRouter(registry, tools).investigate(GOAL, CALM, threshold(50), INITIAL)

    assert len(outcome.steps) == 1
    assert outcome.final.decision == Decision.ACCEPT
    assert outcome.final.providers["energy.route_demand"] == "builtin.momentum-energy@0.1.0"
    assert "accepted at analytical" in outcome.final.justification[0]
    assert not outcome.requires_review


def test_near_boundary_result_escalates_with_justification() -> None:
    registry, tools = toolbox(PhysicsEnergy())

    outcome = FidelityRouter(registry, tools).investigate(GOAL, CALM, threshold(0.3), INITIAL)

    first, second = outcome.steps
    assert first.assessments[0].status == BoundaryStatus.NEAR_BOUNDARY
    assert first.decision == Decision.ESCALATE
    assert "escalating energy.route_demand from analytical to physics" in first.justification[0]
    assert second.providers["energy.route_demand"] == "stub.energy-physics@1.0.0"
    assert any("bypassed lower fidelity builtin.momentum-energy" in s for s in second.selection)
    assert second.decision == Decision.ACCEPT
    assert not outcome.requires_review


def test_fidelity_disagreement_is_flagged_for_review() -> None:
    registry, tools = toolbox(PhysicsEnergy(scale=1.6))

    outcome = FidelityRouter(registry, tools).investigate(GOAL, CALM, threshold(0.3), INITIAL)

    assert [d.measure for d in outcome.disagreements] == ["remaining_energy_wh"]
    assert outcome.disagreements[0].difference > outcome.disagreements[0].tolerance
    assert outcome.requires_review


def test_boundary_without_higher_fidelity_is_exhausted() -> None:
    registry, tools = toolbox()

    outcome = FidelityRouter(registry, tools).investigate(GOAL, CALM, threshold(0.3), INITIAL)

    assert outcome.final.decision == Decision.EXHAUSTED
    assert "no higher-fidelity provider" in outcome.final.justification[0]
    assert outcome.requires_review


def test_unconfirmed_validity_escalates() -> None:
    registry, tools = toolbox(PhysicsEnergy())
    unknown_wind = OperatingContext(airframe="multirotor")

    outcome = FidelityRouter(registry, tools).investigate(
        GOAL, unknown_wind, threshold(50), INITIAL
    )

    assert outcome.steps[0].assessments[0].status == BoundaryStatus.VALIDITY_UNCONFIRMED
    assert outcome.final.providers["energy.route_demand"] == "stub.energy-physics@1.0.0"
    assert outcome.final.decision == Decision.ACCEPT


class PhysicsClosedLoop(ClosedLoopStub):
    manifest = ClosedLoopStub.manifest.model_copy(
        update={
            "id": "stub.closed-loop-physics",
            "fidelity": FidelityClass.PHYSICS,
            "cost": CostClass.LOW,
        }
    )


def test_closed_loop_mechanism_starts_at_high_fidelity() -> None:
    registry, tools = toolbox(ClosedLoopStub(), PhysicsClosedLoop())
    goal = EvaluationGoal(
        measures=("touchdown_error_m",),
        mechanism_id="geometry_clearance.terminal.landing_zone",
    )
    limit = (
        DecisionThreshold(measure="touchdown_error_m", comparator=Comparator.LTE, value=1.5),
    )

    outcome = FidelityRouter(registry, tools).investigate(goal, CALM, limit, INITIAL)

    step = outcome.steps[0]
    assert step.providers["autonomy.closed_loop_flight"] == "stub.closed-loop@0.0.1"
    choice = next(s for s in step.selection if s.startswith("autonomy.closed_loop_flight"))
    assert "mechanism requires high_fidelity_simulation" in choice
    assert "bypassed lower fidelity stub.closed-loop-physics" in choice
    assert step.assessments[0].status == BoundaryStatus.UNQUANTIFIED


def test_perception_mechanisms_require_sensor_realism() -> None:
    capabilities = {c.id: c for c in DEFAULT_CAPABILITY_ONTOLOGY.capabilities}
    visibility = EvaluationGoal(
        measures=("detection_recall",),
        mechanism_id="environment_weather.visibility.degradation",
    )
    mass = EvaluationGoal(
        measures=("mass_margin_kg",), mechanism_id="vehicle_operating_envelope.loading.mass"
    )

    policy = RoutingPolicy()

    assert (
        policy.floors(visibility, capabilities)["sensing.observation_synthesis"].minimum
        == FidelityClass.HIGH_FIDELITY_SIMULATION
    )
    assert "sensing.observation_synthesis" not in policy.floors(mass, capabilities)
