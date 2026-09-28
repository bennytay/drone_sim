import json
import math
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from drone_sim.capabilities import DEFAULT_CAPABILITY_ONTOLOGY, DataKind
from drone_sim.interfaces import (
    PAYLOAD_TYPES,
    Box,
    InterfaceError,
    LocalFrame,
    MeasureSet,
    SeriesRef,
    SiteGeometry,
    ToolAdapter,
    Trajectory,
    WindField,
    run_steps,
)
from drone_sim.ir import ArtifactRef, DeploymentIR
from drone_sim.reference_tools import (
    BUILTIN_TOOLS,
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
    Reproducibility,
    RuntimeSpec,
    ToolManifest,
    ToolRegistry,
)

FIXTURE = Path(__file__).parents[1] / "examples" / "demo_deployment.json"


def demo_deployment(**energy: float) -> DeploymentIR:
    data = json.loads(FIXTURE.read_text())
    data["constraints"].extend(
        [
            {
                "id": "usable-energy",
                "category": "energy",
                "description": "Usable pack energy at release",
                "value": energy.get("usable_wh", 180.0),
                "unit": "Wh",
            },
            {
                "id": "landing-reserve",
                "category": "energy",
                "description": "Minimum landing reserve fraction",
                "value": 0.2,
                "unit": "1",
            },
        ]
    )
    return DeploymentIR.model_validate(data)


class SurveyedSite(ToolAdapter):
    """A third-party site provider that knows nothing about other tools."""

    def __init__(self, obstacles: tuple[Box, ...]):
        self.obstacles = obstacles

    manifest = ToolManifest(
        id="fixture.site-survey",
        version="1.0.0",
        name="Surveyed site boxes",
        description="Obstacle boxes digitised from a site survey.",
        provides=(CapabilityProvision(capability_id="geometry.site_model", measures=("model_age_s",)),),
        airframes=("multirotor",),
        fidelity=FidelityClass.GEOMETRIC,
        runtime=RuntimeSpec(typical_runtime_s=0.01),
        cost=CostClass.NEGLIGIBLE,
        execution_mode=ExecutionMode.IN_PROCESS,
        reproducibility=Reproducibility(deterministic=True),
    )

    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        deployment = inputs["deployment"]
        assert isinstance(deployment, DeploymentIR)
        return {
            "site_geometry": SiteGeometry(
                frame=local_frame(deployment), obstacles=self.obstacles
            ),
            "measures": MeasureSet(),
        }


def test_every_data_kind_has_a_canonical_payload_type() -> None:
    assert set(PAYLOAD_TYPES) == set(DataKind)


def test_builtin_tools_register_against_the_ontology() -> None:
    registry = ToolRegistry(DEFAULT_CAPABILITY_ONTOLOGY)

    for tool in BUILTIN_TOOLS:
        registry.register(tool.manifest)

    assert len(registry.manifests) == len(BUILTIN_TOOLS)


def test_multi_tool_graph_runs_through_canonical_kinds_only() -> None:
    deployment = demo_deployment()
    semantics, energy, clearance = DeploymentSemantics(), MomentumEnergy(), SweptVolumeClearance()
    roof = Box(id="roof", min_enu_m=(5, 10, 0), max_enu_m=(40, 40, 15))

    store = run_steps(
        (
            (semantics, "geometry.route_projection"),
            (semantics, "dynamics.vehicle_envelope"),
            (semantics, "weather.atmosphere"),
            (semantics, "weather.wind_field"),
            (SurveyedSite((roof,)), "geometry.site_model"),
            (energy, "energy.route_demand"),
            (energy, "energy.reserve_assessment"),
            (clearance, "geometry.route_clearance"),
        ),
        {DataKind.DEPLOYMENT: deployment},
    )

    measures = store[DataKind.MEASURE]
    assert isinstance(measures, MeasureSet)
    assert 0 < measures.get("route_energy_wh").value < 180
    assert measures.get("route_energy_wh").error is not None
    assert measures.get("reserve_breach").value is False
    assert measures.get("minimum_clearance_m").value > 0
    assert measures.get("collision").value is False
    assert math.isclose(measures.get("takeoff_mass_kg").value, 4.52)


def test_energy_reserve_breach_follows_usable_energy() -> None:
    deployment = demo_deployment(usable_wh=0.5)
    semantics, energy = DeploymentSemantics(), MomentumEnergy()

    store = run_steps(
        (
            (semantics, "geometry.route_projection"),
            (semantics, "dynamics.vehicle_envelope"),
            (semantics, "weather.atmosphere"),
            (semantics, "weather.wind_field"),
            (energy, "energy.route_demand"),
            (energy, "energy.reserve_assessment"),
        ),
        {DataKind.DEPLOYMENT: deployment},
    )

    assert store[DataKind.MEASURE].get("reserve_breach").value is True


def test_obstacle_on_route_is_a_collision() -> None:
    deployment = demo_deployment()
    semantics = DeploymentSemantics()
    tower = Box(id="tower", min_enu_m=(-12, 18, 0), max_enu_m=(-6, 24, 30))

    store = run_steps(
        (
            (semantics, "geometry.route_projection"),
            (semantics, "dynamics.vehicle_envelope"),
            (SurveyedSite((tower,)), "geometry.site_model"),
            (SweptVolumeClearance(), "geometry.route_clearance"),
        ),
        {DataKind.DEPLOYMENT: deployment},
    )

    assert store[DataKind.MEASURE].get("collision").value is True


def test_missing_upstream_kind_is_reported() -> None:
    with pytest.raises(InterfaceError, match="lacks inputs: route"):
        run_steps(
            ((MomentumEnergy(), "energy.route_demand"),),
            {DataKind.DEPLOYMENT: demo_deployment()},
        )


def test_wrong_payload_type_is_rejected_at_the_port() -> None:
    frame = local_frame(demo_deployment())
    wind = WindField(frame=frame, mean_speed_mps=3, from_direction_deg=90)

    with pytest.raises(InterfaceError, match="expects CanonicalRoute"):
        SweptVolumeClearance().invoke(
            "geometry.route_clearance",
            {"route": wind, "site_geometry": wind, "vehicle_envelope": wind},
        )


def test_mixed_frames_are_rejected() -> None:
    deployment = demo_deployment()
    semantics = DeploymentSemantics()
    route = semantics.invoke("geometry.route_projection", {"deployment": deployment})["route"]
    vehicle = semantics.invoke("dynamics.vehicle_envelope", {"deployment": deployment})[
        "vehicle_envelope"
    ]
    other = LocalFrame(
        origin_latitude_deg=0, origin_longitude_deg=0, vertical_reference="above_ground"
    )

    with pytest.raises(InterfaceError, match="different local frames"):
        SweptVolumeClearance().invoke(
            "geometry.route_clearance",
            {"route": route, "site_geometry": SiteGeometry(frame=other), "vehicle_envelope": vehicle},
        )


def test_wind_direction_is_meteorological() -> None:
    frame = local_frame(demo_deployment())
    from_north = WindField(frame=frame, mean_speed_mps=10, from_direction_deg=0)

    east, north, _ = from_north.velocity_enu_mps
    assert math.isclose(north, -10) and abs(east) < 1e-9


def test_large_series_are_passed_by_pinned_reference() -> None:
    frame = local_frame(demo_deployment())
    unpinned = ArtifactRef(id="log", uri="telemetry/flight.ulg", role="telemetry")

    with pytest.raises(ValidationError, match="sha256"):
        SeriesRef(artifact=unpinned, fields=("t_s",), sample_count=10, start_s=0, end_s=1)

    pinned = unpinned.model_copy(update={"sha256": "b" * 64})
    trajectory = Trajectory(
        frame=frame,
        series=SeriesRef(
            artifact=pinned, fields=("t_s", "east_m"), sample_count=90_000, start_s=0, end_s=900
        ),
    )
    assert trajectory.states == ()


def test_undeclared_measures_are_rejected() -> None:
    class Leaky(SurveyedSite):
        def compute(self, capability_id, inputs):
            outputs = dict(super().compute(capability_id, inputs))
            outputs["measures"] = MeasureSet(
                measures=({"name": "minimum_clearance_m", "value": 1.0},)
            )
            return outputs

    with pytest.raises(InterfaceError, match="undeclared measures"):
        Leaky(()).invoke("geometry.site_model", {"deployment": demo_deployment()})
