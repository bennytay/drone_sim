"""Canonical typed payloads and the adapter contract between tools.

Conventions every payload and provider must follow:

- units are SI and encoded in field names (``_m``, ``_mps``, ``_wh``, ``_s``);
- positions are local East-North-Up metres in a ``LocalFrame`` anchored at a
  geodetic origin with an explicit vertical reference;
- time is seconds from a UTC ``epoch`` carried by the time-indexed payload;
- headings and wind directions are degrees clockwise from true north, and
  wind direction is the direction the wind blows *from*;
- large time series and assets are passed as hashed ``SeriesRef`` or
  ``ArtifactRef`` references rather than copied inline.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import cached_property
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from drone_sim.capabilities import (
    DEFAULT_CAPABILITY_ONTOLOGY,
    CapabilityOntology,
    DataKind,
    Port,
)
from drone_sim.ir import ArtifactRef, DeploymentIR, StrictModel
from drone_sim.registry import CapabilityProvision, ToolManifest, resolve_manifest

Vector3 = tuple[float, float, float]
MAX_INLINE_SAMPLES = 10_000


class LocalFrame(StrictModel):
    """East-North-Up frame shared by every positional payload in a test."""

    origin_latitude_deg: float = Field(ge=-90, le=90)
    origin_longitude_deg: float = Field(ge=-180, le=180)
    origin_altitude_m: float = 0.0
    vertical_reference: Literal["above_ground", "mean_sea_level", "ellipsoid"]


class SeriesRef(StrictModel):
    """Hashed reference to a time series too large to pass inline."""

    artifact: ArtifactRef
    fields: tuple[str, ...] = Field(min_length=1)
    sample_count: int = Field(ge=1)
    start_s: float
    end_s: float

    @model_validator(mode="after")
    def pinned_and_ordered(self) -> Self:
        if self.artifact.sha256 is None:
            raise ValueError("series references must pin a sha256 digest")
        if self.end_s < self.start_s:
            raise ValueError("series end_s cannot precede start_s")
        return self


class RouteWaypoint(StrictModel):
    id: str = Field(min_length=1)
    position_enu_m: Vector3
    target_speed_mps: float | None = Field(default=None, gt=0)
    acceptance_radius_m: float | None = Field(default=None, gt=0)
    action: str | None = None


class CanonicalRoute(StrictModel):
    kind: Literal[DataKind.ROUTE] = DataKind.ROUTE
    frame: LocalFrame
    waypoints: tuple[RouteWaypoint, ...] = Field(min_length=2)

    def legs(self) -> tuple[tuple[RouteWaypoint, RouteWaypoint], ...]:
        return tuple(zip(self.waypoints, self.waypoints[1:]))

    @property
    def length_m(self) -> float:
        return sum(math.dist(a.position_enu_m, b.position_enu_m) for a, b in self.legs())


class VehicleState(StrictModel):
    t_s: float
    position_enu_m: Vector3
    velocity_enu_mps: Vector3 = (0.0, 0.0, 0.0)
    attitude_rpy_deg: Vector3 | None = None


class Trajectory(StrictModel):
    """Flown or predicted vehicle states, inline or by reference."""

    kind: Literal[DataKind.TRAJECTORY] = DataKind.TRAJECTORY
    frame: LocalFrame
    epoch: datetime | None = None
    states: tuple[VehicleState, ...] = Field(default=(), max_length=MAX_INLINE_SAMPLES)
    series: SeriesRef | None = None

    @model_validator(mode="after")
    def exactly_one_representation(self) -> Self:
        if bool(self.states) == bool(self.series):
            raise ValueError("trajectory requires inline states or a series reference")
        times = [state.t_s for state in self.states]
        if times != sorted(times):
            raise ValueError("trajectory states must be time ordered")
        return self


class Box(StrictModel):
    """Axis-aligned volume in the local frame."""

    id: str = Field(min_length=1)
    min_enu_m: Vector3
    max_enu_m: Vector3

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if any(lo > hi for lo, hi in zip(self.min_enu_m, self.max_enu_m)):
            raise ValueError("box minimum must not exceed maximum on any axis")
        return self

    def distance_m(self, point: Vector3) -> float:
        return math.sqrt(
            sum(
                max(lo - p, 0.0, p - hi) ** 2
                for p, lo, hi in zip(point, self.min_enu_m, self.max_enu_m)
            )
        )


class SiteGeometry(StrictModel):
    """Occupancy as primitive obstacles plus an optional referenced mesh."""

    kind: Literal[DataKind.SITE_GEOMETRY] = DataKind.SITE_GEOMETRY
    frame: LocalFrame
    obstacles: tuple[Box, ...] = ()
    ground_up_m: float = 0.0
    mesh: ArtifactRef | None = None


class OperatingVolume(StrictModel):
    kind: Literal[DataKind.OPERATING_VOLUME] = DataKind.OPERATING_VOLUME
    frame: LocalFrame
    authorized: tuple[Box, ...] = ()
    excluded: tuple[Box, ...] = ()


class WindField(StrictModel):
    """Uniform mean wind with optional gust statistics or a referenced grid."""

    kind: Literal[DataKind.WIND_FIELD] = DataKind.WIND_FIELD
    frame: LocalFrame
    mean_speed_mps: float = Field(ge=0)
    from_direction_deg: float = Field(ge=0, lt=360)
    gust_speed_mps: float | None = Field(default=None, ge=0)
    turbulence_intensity: float | None = Field(default=None, ge=0)
    grid: SeriesRef | None = None

    @property
    def velocity_enu_mps(self) -> Vector3:
        toward = math.radians(self.from_direction_deg + 180.0)
        return (
            self.mean_speed_mps * math.sin(toward),
            self.mean_speed_mps * math.cos(toward),
            0.0,
        )


class Atmosphere(StrictModel):
    kind: Literal[DataKind.ATMOSPHERE] = DataKind.ATMOSPHERE
    temperature_c: float
    air_density_kg_m3: float = Field(gt=0)
    precipitation_mm_h: float = Field(default=0.0, ge=0)
    visibility_m: float | None = Field(default=None, ge=0)
    illuminance_lux: float | None = Field(default=None, ge=0)


class VehicleEnvelope(StrictModel):
    kind: Literal[DataKind.VEHICLE_ENVELOPE] = DataKind.VEHICLE_ENVELOPE
    airframe: Literal["multirotor", "fixed_wing", "vtol"]
    takeoff_mass_kg: float = Field(gt=0)
    max_takeoff_mass_kg: float | None = Field(default=None, gt=0)
    extent_m: Vector3
    max_speed_mps: float | None = Field(default=None, gt=0)
    max_wind_speed_mps: float | None = Field(default=None, gt=0)
    usable_energy_wh: float | None = Field(default=None, gt=0)
    reserve_fraction: float | None = Field(default=None, ge=0, lt=1)

    @property
    def radius_m(self) -> float:
        return max(self.extent_m[0], self.extent_m[1]) / 2


class BatterySample(StrictModel):
    t_s: float
    remaining_energy_wh: float
    power_w: float = Field(ge=0)


class BatteryState(StrictModel):
    kind: Literal[DataKind.BATTERY_STATE] = DataKind.BATTERY_STATE
    usable_energy_wh: float = Field(gt=0)
    consumed_energy_wh: float = Field(ge=0)
    peak_power_w: float = Field(ge=0)
    samples: tuple[BatterySample, ...] = Field(default=(), max_length=MAX_INLINE_SAMPLES)
    series: SeriesRef | None = None

    @property
    def remaining_energy_wh(self) -> float:
        return self.usable_energy_wh - self.consumed_energy_wh


class SensorObservation(StrictModel):
    kind: Literal[DataKind.SENSOR_OBSERVATION] = DataKind.SENSOR_OBSERVATION
    sensor_id: str = Field(min_length=1)
    modality: Literal["rgb", "thermal", "lidar", "radar", "depth", "multispectral"]
    frames: SeriesRef | None = None
    frame_count: int = Field(ge=0)
    valid_frame_fraction: float = Field(ge=0, le=1)


class Detection(StrictModel):
    t_s: float
    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    position_enu_m: Vector3 | None = None


class DetectionSet(StrictModel):
    kind: Literal[DataKind.DETECTION] = DataKind.DETECTION
    sensor_id: str = Field(min_length=1)
    detections: tuple[Detection, ...] = Field(default=(), max_length=MAX_INLINE_SAMPLES)
    series: SeriesRef | None = None


class LocalizationEstimate(StrictModel):
    kind: Literal[DataKind.LOCALIZATION_ESTIMATE] = DataKind.LOCALIZATION_ESTIMATE
    frame: LocalFrame
    source: Literal["absolute", "relative", "fused"]
    horizontal_error_p95_m: float = Field(ge=0)
    vertical_error_p95_m: float = Field(ge=0)
    series: SeriesRef | None = None


class LinkState(StrictModel):
    kind: Literal[DataKind.LINK_STATE] = DataKind.LINK_STATE
    link: Literal["command_control", "telemetry", "payload"]
    minimum_margin_db: float
    packet_loss_fraction: float = Field(ge=0, le=1)
    longest_outage_s: float = Field(ge=0)
    series: SeriesRef | None = None


class ExternalActor(StrictModel):
    id: str = Field(min_length=1)
    category: Literal["crewed_aircraft", "drone", "person", "vehicle", "wildlife", "obstacle"]
    trajectory: Trajectory


class Traffic(StrictModel):
    kind: Literal[DataKind.TRAFFIC] = DataKind.TRAFFIC
    actors: tuple[ExternalActor, ...] = ()


class ConditionSamples(StrictModel):
    kind: Literal[DataKind.CONDITION_SAMPLES] = DataKind.CONDITION_SAMPLES
    seed: int
    variables: tuple[str, ...] = Field(min_length=1)
    samples: tuple[tuple[float, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if any(len(sample) != len(self.variables) for sample in self.samples):
            raise ValueError("every condition sample must bind every variable")
        return self


class MeasureError(StrictModel):
    kind: Literal["absolute_bound", "standard_deviation"]
    value: float = Field(ge=0)


class Measure(StrictModel):
    """One observable produced by a provider, in canonical units."""

    name: str = Field(min_length=1)
    value: float | bool
    unit: str | None = None
    error: MeasureError | None = None


class MeasureSet(StrictModel):
    kind: Literal[DataKind.MEASURE] = DataKind.MEASURE
    measures: tuple[Measure, ...] = ()

    def get(self, name: str) -> Measure:
        for measure in self.measures:
            if measure.name == name:
                return measure
        raise KeyError(name)


class Violation(StrictModel):
    constraint_id: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    observed: float | bool | str
    limit: float | bool | str
    unit: str | None = None


class ConstraintViolations(StrictModel):
    kind: Literal[DataKind.CONSTRAINT_VIOLATION] = DataKind.CONSTRAINT_VIOLATION
    violations: tuple[Violation, ...] = ()


class MissionOutcome(StrictModel):
    kind: Literal[DataKind.MISSION_OUTCOME] = DataKind.MISSION_OUTCOME
    completed: bool
    completion_ratio: float = Field(ge=0, le=1)
    duration_s: float = Field(ge=0)
    aborted_reason: str | None = None


PAYLOAD_TYPES: dict[DataKind, type[BaseModel]] = {
    DataKind.DEPLOYMENT: DeploymentIR,
    DataKind.ROUTE: CanonicalRoute,
    DataKind.TRAJECTORY: Trajectory,
    DataKind.SITE_GEOMETRY: SiteGeometry,
    DataKind.OPERATING_VOLUME: OperatingVolume,
    DataKind.WIND_FIELD: WindField,
    DataKind.ATMOSPHERE: Atmosphere,
    DataKind.VEHICLE_ENVELOPE: VehicleEnvelope,
    DataKind.BATTERY_STATE: BatteryState,
    DataKind.SENSOR_OBSERVATION: SensorObservation,
    DataKind.DETECTION: DetectionSet,
    DataKind.LOCALIZATION_ESTIMATE: LocalizationEstimate,
    DataKind.LINK_STATE: LinkState,
    DataKind.TRAFFIC: Traffic,
    DataKind.CONDITION_SAMPLES: ConditionSamples,
    DataKind.CONSTRAINT_VIOLATION: ConstraintViolations,
    DataKind.MISSION_OUTCOME: MissionOutcome,
    DataKind.MEASURE: MeasureSet,
}


class InterfaceError(ValueError):
    """A payload does not satisfy the canonical contract of a port."""


def check_payload(port: Port, value: object) -> BaseModel:
    expected = PAYLOAD_TYPES[port.kind]
    if not isinstance(value, expected):
        raise InterfaceError(
            f"port {port.name} expects {expected.__name__}, got {type(value).__name__}"
        )
    return value


def shared_frame(values: Mapping[str, BaseModel]) -> LocalFrame | None:
    """Return the single frame used by positional payloads, or fail."""

    frames = {
        name: value.frame for name, value in values.items() if hasattr(value, "frame")
    }
    distinct = set(frames.values())
    if len(distinct) > 1:
        raise InterfaceError(
            f"payloads use different local frames: {', '.join(sorted(frames))}"
        )
    return distinct.pop() if distinct else None


class ToolAdapter(ABC):
    """Wraps one provider behind its manifest's canonical ports.

    Semantic conversion from Deployment IR into canonical payloads is itself
    a registered capability. Anything specific to a model's native API or
    file format belongs inside ``compute`` and never crosses the boundary.
    """

    manifest: ToolManifest
    ontology: CapabilityOntology = DEFAULT_CAPABILITY_ONTOLOGY

    @cached_property
    def contract(self) -> ToolManifest:
        """The manifest with ports and measures resolved against the ontology."""

        return resolve_manifest(self.manifest, self.ontology)

    def invoke(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> dict[str, BaseModel]:
        provision = self.contract.provision(capability_id)
        bound = self._bind_inputs(provision, inputs)
        frame = shared_frame(bound)
        outputs = self.compute(capability_id, bound)
        checked: dict[str, BaseModel] = {}
        for port in provision.outputs:
            if port.name not in outputs:
                raise InterfaceError(
                    f"{self.manifest.key} did not produce {capability_id} output "
                    f"{port.name}"
                )
            checked[port.name] = check_payload(port, outputs[port.name])
        if frame is not None and shared_frame({**bound, **checked}) != frame:
            raise InterfaceError(f"{self.manifest.key} changed the local frame")
        self._check_measures(provision, checked)
        return checked

    def _bind_inputs(
        self, provision: CapabilityProvision, inputs: Mapping[str, BaseModel]
    ) -> dict[str, BaseModel]:
        bound: dict[str, BaseModel] = {}
        for port in provision.inputs:
            if port.name not in inputs:
                raise InterfaceError(
                    f"{self.manifest.key} requires {provision.capability_id} input "
                    f"{port.name}"
                )
            bound[port.name] = check_payload(port, inputs[port.name])
        return bound

    def _check_measures(
        self, provision: CapabilityProvision, outputs: Mapping[str, BaseModel]
    ) -> None:
        for value in outputs.values():
            if isinstance(value, MeasureSet):
                undeclared = {m.name for m in value.measures} - set(provision.measures)
                if undeclared:
                    raise InterfaceError(
                        f"{self.manifest.key} emitted undeclared measures: "
                        f"{', '.join(sorted(undeclared))}"
                    )

    @abstractmethod
    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        """Run the provider on validated canonical inputs."""


def run_steps(
    steps: Sequence[tuple[ToolAdapter, str]],
    available: Mapping[DataKind, BaseModel],
) -> dict[DataKind, BaseModel]:
    """Wire providers purely through canonical data kinds.

    Each step's inputs are looked up by port kind in the shared store and its
    outputs are written back by kind; measure sets accumulate. No step knows
    which provider produced its inputs.
    """

    store = dict(available)
    for tool, capability_id in steps:
        provision = tool.contract.provision(capability_id)
        missing = [port.name for port in provision.inputs if port.kind not in store]
        if missing:
            raise InterfaceError(
                f"{capability_id} via {tool.manifest.key} lacks inputs: "
                f"{', '.join(missing)}"
            )
        outputs = tool.invoke(
            capability_id, {port.name: store[port.kind] for port in provision.inputs}
        )
        for port in provision.outputs:
            value = outputs[port.name]
            previous = store.get(port.kind)
            if isinstance(value, MeasureSet) and isinstance(previous, MeasureSet):
                value = MeasureSet(measures=previous.measures + value.measures)
            store[port.kind] = value
    return store
