from collections.abc import Mapping

from pydantic import BaseModel

from drone_sim.capabilities import DataKind
from drone_sim.graph import (
    INITIAL,
    EvaluationGoal,
    GapKind,
    GraphPlanner,
    NodeStatus,
    execute,
)
from drone_sim.hypothesis import FailureHypothesis, ObservationCondition
from drone_sim.interfaces import (
    Box,
    MeasureSet,
    MissionOutcome,
    SensorObservation,
    ToolAdapter,
    Trajectory,
    VehicleState,
)
from drone_sim.reference_tools import (
    DeploymentSemantics,
    MomentumEnergy,
    SweptVolumeClearance,
    local_frame,
)
from drone_sim.registry import (
    CapabilityProvision,
    CostClass,
    ExecutionMode,
    FidelityClass,
    OperatingContext,
    Reproducibility,
    RuntimeSpec,
    ToolManifest,
    ToolRegistry,
)

from test_hypothesis import hypothesis
from test_interfaces import SurveyedSite, demo_deployment

CALM = OperatingContext(airframe="multirotor", variables={"wind_speed_mps": 6.5})
ROOF = Box(id="roof", min_enu_m=(5, 10, 0), max_enu_m=(40, 40, 15))


def toolbox(*extra: ToolAdapter) -> tuple[ToolRegistry, dict[str, ToolAdapter]]:
    tools = (
        DeploymentSemantics(),
        MomentumEnergy(),
        SweptVolumeClearance(),
        SurveyedSite((ROOF,)),
        *extra,
    )
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool.manifest)
    return registry, {tool.manifest.key: tool for tool in tools}


def reserve_hypothesis() -> FailureHypothesis:
    return hypothesis("hyp_reserve").model_copy(
        update={
            "mechanism_id": "energy_battery.reserve.route_demand",
            "confirm_if": (
                ObservationCondition(
                    observable="reserve_breach",
                    description="Landing reserve falls below the declared fraction.",
                ),
            ),
            "falsify_if": (
                ObservationCondition(
                    observable="remaining_energy_wh",
                    description="Remaining energy exceeds reserve across conditions.",
                ),
            ),
        }
    )


def test_hypothesis_becomes_an_executed_evidence_path() -> None:
    registry, tools = toolbox()
    goal = EvaluationGoal.for_hypothesis(reserve_hypothesis())

    plan = GraphPlanner(registry).plan(goal, CALM)
    record = execute(plan, tools, {DataKind.DEPLOYMENT: demo_deployment()})

    assert plan.complete and record.succeeded
    assert [node.id for node in plan.nodes][-2:] == [
        "energy.route_demand",
        "energy.reserve_assessment",
    ]
    remaining = record.measure("remaining_energy_wh")
    assert remaining.provider_key == "builtin.momentum-energy@0.1.0"
    assert remaining.error is not None
    assert "geometry.route_projection" in remaining.lineage
    assert remaining.fully_quantified
    assert record.measure("reserve_breach").value is False


def test_provider_ports_limit_expansion() -> None:
    registry, _ = toolbox()

    plan = GraphPlanner(registry).plan(
        EvaluationGoal(measures=("route_energy_wh",)), CALM
    )

    assert "geometry.site_model" not in {node.id for node in plan.nodes}
    wind = plan.node("weather.wind_field")
    assert [edge.source for edge in wind.inputs] == [INITIAL]


def test_clearance_path_composes_a_third_party_site_provider() -> None:
    registry, tools = toolbox()

    plan = GraphPlanner(registry).plan(
        EvaluationGoal(measures=("minimum_clearance_m", "collision")), CALM
    )
    record = execute(plan, tools, {DataKind.DEPLOYMENT: demo_deployment()})

    assert plan.node("geometry.site_model").provider_key == "fixture.site-survey@1.0.0"
    assert record.measure("minimum_clearance_m").value > 0
    assert record.measure("minimum_clearance_m").error.value == 0.25
    assert record.succeeded


def test_unsatisfied_capabilities_are_surfaced() -> None:
    registry, _ = toolbox()

    plan = GraphPlanner(registry).plan(
        EvaluationGoal(measures=("detection_recall", "teleport_count")), CALM
    )

    assert not plan.complete
    kinds = {(gap.kind, gap.subject) for gap in plan.gaps}
    assert (GapKind.UNMEASURABLE, "teleport_count") in kinds
    assert (GapKind.NO_PROVIDER, "detection_recall") in kinds


def test_conditional_provider_gap_explains_the_rejection() -> None:
    registry, _ = toolbox()
    vtol = OperatingContext(airframe="vtol", variables={"wind_speed_mps": 4})

    plan = GraphPlanner(registry).plan(EvaluationGoal(measures=("route_energy_wh",)), vtol)

    reasons = " ".join(gap.reason for gap in plan.gaps)
    assert "builtin.momentum-energy@0.1.0 (airframe" in reasons


def test_outside_validity_is_not_planned_silently() -> None:
    registry, _ = toolbox()
    gusty = OperatingContext(airframe="multirotor", variables={"wind_speed_mps": 15})

    plan = GraphPlanner(registry).plan(EvaluationGoal(measures=("route_energy_wh",)), gusty)

    assert not plan.complete
    assert "outside validity: wind_speed_mps" in " ".join(gap.reason for gap in plan.gaps)


class ClosedLoopStub(ToolAdapter):
    """Stands in for a closed-loop simulator; returns a hover trajectory."""

    manifest = ToolManifest(
        id="stub.closed-loop",
        version="0.0.1",
        name="Closed-loop stub",
        description="Deterministic stand-in for a closed-loop flight provider.",
        provides=(
            CapabilityProvision(
                capability_id="autonomy.closed_loop_flight",
                measures=("touchdown_error_m",),
            ),
        ),
        airframes=("multirotor",),
        fidelity=FidelityClass.HIGH_FIDELITY_SIMULATION,
        runtime=RuntimeSpec(typical_runtime_s=600, compute="gpu"),
        cost=CostClass.HIGH,
        execution_mode=ExecutionMode.REMOTE_SERVICE,
        reproducibility=Reproducibility(deterministic=False, seed_controlled=True),
    )

    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        frame = inputs["route"].frame
        return {
            "trajectory": Trajectory(
                frame=frame, states=(VehicleState(t_s=0, position_enu_m=(0, 0, 0)),)
            ),
            "sensor_observation": SensorObservation(
                sensor_id="cam", modality="rgb", frame_count=0, valid_frame_fraction=1
            ),
            "mission_outcome": MissionOutcome(completed=True, completion_ratio=1, duration_s=60),
            "measures": MeasureSet(measures=({"name": "touchdown_error_m", "value": 0.4},)),
        }


def test_closed_loop_composite_is_one_node() -> None:
    registry, tools = toolbox(ClosedLoopStub())
    goal = EvaluationGoal(
        measures=("touchdown_error_m",),
        mechanism_id="geometry_clearance.terminal.landing_zone",
    )

    plan = GraphPlanner(registry).plan(goal, CALM)
    record = execute(plan, tools, {DataKind.DEPLOYMENT: demo_deployment()})

    ids = {node.id for node in plan.nodes}
    assert "autonomy.closed_loop_flight" in ids
    assert "dynamics.trajectory_response" not in ids
    assert record.measure("touchdown_error_m").value == 0.4
    assert not record.measure("touchdown_error_m").fully_quantified


def test_failed_provider_skips_downstream_and_withholds_evidence() -> None:
    class Broken(SurveyedSite):
        def compute(self, capability_id, inputs):
            raise RuntimeError("survey service unavailable")

    registry, tools = toolbox()
    tools["fixture.site-survey@1.0.0"] = Broken(())

    plan = GraphPlanner(registry).plan(EvaluationGoal(measures=("minimum_clearance_m",)), CALM)
    record = execute(plan, tools, {DataKind.DEPLOYMENT: demo_deployment()})

    statuses = {node.node_id: node.status for node in record.nodes}
    assert statuses["geometry.site_model"] == NodeStatus.FAILED
    assert statuses["geometry.route_clearance"] == NodeStatus.SKIPPED
    assert record.evidence == ()
    assert not record.succeeded


def test_execution_is_reproducible() -> None:
    registry, tools = toolbox()
    plan = GraphPlanner(registry).plan(EvaluationGoal.for_hypothesis(reserve_hypothesis()), CALM)
    initial = {DataKind.DEPLOYMENT: demo_deployment()}

    assert execute(plan, tools, initial) == execute(plan, tools, initial)
