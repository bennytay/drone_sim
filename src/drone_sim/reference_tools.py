"""Deterministic built-in providers that exercise the canonical interfaces.

``DeploymentSemantics`` is the semantic conversion boundary from Deployment IR
into canonical payloads. The other providers are credible low-fidelity models
that consume only canonical payloads.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import BaseModel

from drone_sim.interfaces import (
    Atmosphere,
    BatterySample,
    BatteryState,
    CanonicalRoute,
    LocalFrame,
    Measure,
    MeasureError,
    MeasureSet,
    RouteWaypoint,
    SiteGeometry,
    ToolAdapter,
    VehicleEnvelope,
    WindField,
)
from drone_sim.ir import DeploymentIR
from drone_sim.registry import (
    CapabilityProvision,
    CostClass,
    ErrorSpec,
    ExecutionMode,
    FidelityClass,
    Interval,
    Region,
    Reproducibility,
    RuntimeSpec,
    ToolManifest,
    UncertaintyKind,
)

EARTH_RADIUS_M = 6_371_008.8
GRAVITY_MPS2 = 9.80665
SEA_LEVEL_PRESSURE_PA = 101_325.0
DRY_AIR_GAS_CONSTANT = 287.05
DEFAULT_SPEED_MPS = 5.0

_ALL_AIRFRAMES = ("multirotor", "fixed_wing", "vtol")
_REPRODUCIBLE = Reproducibility(deterministic=True)


def local_frame(deployment: DeploymentIR) -> LocalFrame:
    """Anchor the ENU frame at the first waypoint using the route's datum."""

    points = deployment.mission.route.points
    references = {point.position.altitude_reference for point in points}
    if len(references) != 1:
        raise ValueError("route waypoints mix vertical references")
    origin = points[0].position
    return LocalFrame(
        origin_latitude_deg=origin.latitude_deg,
        origin_longitude_deg=origin.longitude_deg,
        vertical_reference=origin.altitude_reference,
    )


def to_enu(
    frame: LocalFrame, latitude_deg: float, longitude_deg: float, altitude_m: float
) -> tuple[float, float, float]:
    """Local tangent-plane projection, adequate for site-scale deployments."""

    east = (
        math.radians(longitude_deg - frame.origin_longitude_deg)
        * math.cos(math.radians(frame.origin_latitude_deg))
        * EARTH_RADIUS_M
    )
    north = math.radians(latitude_deg - frame.origin_latitude_deg) * EARTH_RADIUS_M
    return (east, north, altitude_m - frame.origin_altitude_m)


_UNIT_SUFFIXES = (
    ("_kg_m3", "kg/m3"),
    ("_mm_h", "mm/h"),
    ("_mps", "m/s"),
    ("_wh", "Wh"),
    ("_kg", "kg"),
    ("_deg", "deg"),
    ("_m", "m"),
    ("_s", "s"),
    ("_w", "W"),
    ("_c", "C"),
)


def _measures(**values: float | bool | None) -> MeasureSet:
    """Build a measure set, deriving canonical units from name suffixes."""

    return MeasureSet(
        measures=tuple(
            Measure(
                name=name,
                value=value,
                unit=next(
                    (unit for suffix, unit in _UNIT_SUFFIXES if name.endswith(suffix)),
                    None,
                ),
            )
            for name, value in values.items()
            if value is not None
        )
    )


class DeploymentSemantics(ToolAdapter):
    """Converts Deployment IR into canonical route, vehicle, and weather payloads."""

    manifest = ToolManifest(
        id="builtin.deployment-semantics",
        version="0.1.0",
        name="Deployment IR semantic conversion",
        description="Deterministic conversion of Deployment IR into canonical payloads.",
        provides=(
            CapabilityProvision(capability_id="geometry.route_projection"),
            CapabilityProvision(capability_id="dynamics.vehicle_envelope"),
            CapabilityProvision(capability_id="weather.atmosphere"),
            CapabilityProvision(
                capability_id="weather.wind_field",
                inputs=({"name": "deployment", "kind": "deployment"},),
            ),
        ),
        airframes=_ALL_AIRFRAMES,
        fidelity=FidelityClass.RULE,
        runtime=RuntimeSpec(typical_runtime_s=0.001),
        cost=CostClass.NEGLIGIBLE,
        execution_mode=ExecutionMode.IN_PROCESS,
        reproducibility=_REPRODUCIBLE,
    )

    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        deployment = inputs["deployment"]
        assert isinstance(deployment, DeploymentIR)
        match capability_id:
            case "geometry.route_projection":
                return self._route(deployment)
            case "dynamics.vehicle_envelope":
                return self._vehicle(deployment)
            case "weather.atmosphere":
                return self._atmosphere(deployment)
            case "weather.wind_field":
                return self._wind(deployment)
        raise KeyError(capability_id)

    def _route(self, deployment: DeploymentIR) -> dict[str, BaseModel]:
        frame = local_frame(deployment)
        route = CanonicalRoute(
            frame=frame,
            waypoints=tuple(
                RouteWaypoint(
                    id=point.id,
                    position_enu_m=to_enu(
                        frame,
                        point.position.latitude_deg,
                        point.position.longitude_deg,
                        point.position.altitude_m,
                    ),
                    target_speed_mps=point.target_speed_mps,
                    acceptance_radius_m=point.acceptance_radius_m,
                    action=point.action,
                )
                for point in deployment.mission.route.points
            ),
        )
        duration = sum(
            math.dist(a.position_enu_m, b.position_enu_m)
            / (b.target_speed_mps or DEFAULT_SPEED_MPS)
            for a, b in route.legs()
        )
        heading = next(
            (
                math.degrees(
                    math.atan2(
                        b.position_enu_m[0] - a.position_enu_m[0],
                        b.position_enu_m[1] - a.position_enu_m[1],
                    )
                )
                % 360
                for a, b in route.legs()
                if math.dist(a.position_enu_m[:2], b.position_enu_m[:2]) > 0
            ),
            None,
        )
        return {
            "route": route,
            "measures": _measures(
                route_length_m=route.length_m,
                route_duration_s=duration,
                route_heading_deg=heading,
            ),
        }

    def _vehicle(self, deployment: DeploymentIR) -> dict[str, BaseModel]:
        vehicle = deployment.vehicle
        mass = vehicle.mass_kg + sum(payload.mass_kg for payload in deployment.payloads)
        energy = {
            constraint.unit: float(constraint.value)
            for constraint in deployment.constraints
            if constraint.category == "energy"
            and isinstance(constraint.value, int | float)
            and constraint.unit in {"Wh", "1"}
        }
        envelope = VehicleEnvelope(
            airframe=vehicle.airframe,
            takeoff_mass_kg=mass,
            max_takeoff_mass_kg=vehicle.max_takeoff_mass_kg,
            extent_m=vehicle.dimensions_m,
            max_speed_mps=vehicle.max_speed_mps,
            max_wind_speed_mps=vehicle.max_wind_speed_mps,
            usable_energy_wh=energy.get("Wh"),
            reserve_fraction=energy.get("1"),
        )
        limit = vehicle.max_takeoff_mass_kg
        return {
            "vehicle_envelope": envelope,
            "measures": _measures(
                takeoff_mass_kg=mass,
                mass_margin_kg=None if limit is None else limit - mass,
                takeoff_rejected=None if limit is None else mass > limit,
            ),
        }

    def _atmosphere(self, deployment: DeploymentIR) -> dict[str, BaseModel]:
        conditions = deployment.conditions
        if conditions is None or conditions.temperature_c is None:
            raise ValueError("atmosphere requires an observed or forecast temperature")
        reference = deployment.site.reference_point
        elevation = (
            reference.altitude_m
            if reference and reference.altitude_reference == "mean_sea_level"
            else 0.0
        )
        kelvin = conditions.temperature_c + 273.15
        pressure = SEA_LEVEL_PRESSURE_PA * math.exp(
            -GRAVITY_MPS2 * elevation / (DRY_AIR_GAS_CONSTANT * kelvin)
        )
        atmosphere = Atmosphere(
            temperature_c=conditions.temperature_c,
            air_density_kg_m3=pressure / (DRY_AIR_GAS_CONSTANT * kelvin),
            precipitation_mm_h=conditions.precipitation_mm_h or 0.0,
            visibility_m=conditions.visibility_m,
        )
        return {
            "atmosphere": atmosphere,
            "measures": _measures(
                temperature_c=atmosphere.temperature_c,
                air_density_kg_m3=atmosphere.air_density_kg_m3,
                precipitation_mm_h=atmosphere.precipitation_mm_h,
                visibility_m=atmosphere.visibility_m,
            ),
        }

    def _wind(self, deployment: DeploymentIR) -> dict[str, BaseModel]:
        conditions = deployment.conditions
        if conditions is None or conditions.wind_speed_mps is None:
            raise ValueError("wind field requires an observed or forecast wind speed")
        wind = WindField(
            frame=local_frame(deployment),
            mean_speed_mps=conditions.wind_speed_mps,
            from_direction_deg=conditions.wind_direction_deg or 0.0,
        )
        return {
            "wind_field": wind,
            "measures": _measures(wind_speed_mps=wind.mean_speed_mps),
        }


class MomentumEnergy(ToolAdapter):
    """Momentum-theory hover power plus parasitic drag, integrated per leg."""

    FIGURE_OF_MERIT = 0.6
    CLIMB_EFFICIENCY = 0.7
    DRAG_COEFFICIENT = 1.0
    RELATIVE_ERROR = 0.15

    manifest = ToolManifest(
        id="builtin.momentum-energy",
        version="0.1.0",
        name="Momentum-theory route energy",
        description="Closed-form multirotor power integrated over route legs in steady wind.",
        provides=(
            CapabilityProvision(
                capability_id="energy.route_demand",
                conditions=Region(airframes=("multirotor",)),
            ),
            CapabilityProvision(
                capability_id="energy.reserve_assessment",
                measures=("reserve_breach", "forced_landing", "landing_reserve_wh"),
            ),
        ),
        airframes=("multirotor",),
        validity_region=Region(
            bounds=(
                Interval(variable="wind_speed_mps", minimum=0, maximum=12, unit="m/s"),
            )
        ),
        fidelity=FidelityClass.ANALYTICAL,
        errors=(
            ErrorSpec(
                measure="route_energy_wh",
                kind=UncertaintyKind.RELATIVE_BOUND,
                value=RELATIVE_ERROR,
                basis="Momentum theory omits profile losses and transient manoeuvres",
            ),
        ),
        runtime=RuntimeSpec(typical_runtime_s=0.01),
        cost=CostClass.NEGLIGIBLE,
        execution_mode=ExecutionMode.IN_PROCESS,
        reproducibility=_REPRODUCIBLE,
    )

    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        if capability_id == "energy.route_demand":
            return self._demand(inputs)
        return self._reserve(inputs)

    def _demand(self, inputs: Mapping[str, BaseModel]) -> dict[str, BaseModel]:
        route = inputs["route"]
        vehicle = inputs["vehicle_envelope"]
        wind = inputs["wind_field"]
        atmosphere = inputs["atmosphere"]
        assert isinstance(route, CanonicalRoute)
        assert isinstance(vehicle, VehicleEnvelope)
        assert isinstance(wind, WindField)
        assert isinstance(atmosphere, Atmosphere)
        if vehicle.usable_energy_wh is None:
            raise ValueError("route demand requires usable battery energy")
        rho = atmosphere.air_density_kg_m3
        weight = vehicle.takeoff_mass_kg * GRAVITY_MPS2
        disk_area = math.pi * vehicle.radius_m**2
        frontal_area = vehicle.extent_m[0] * vehicle.extent_m[2]
        hover = weight**1.5 / math.sqrt(2 * rho * disk_area) / self.FIGURE_OF_MERIT
        wind_vector = wind.velocity_enu_mps
        elapsed = 0.0
        consumed = 0.0
        peak = 0.0
        samples = [BatterySample(t_s=0.0, remaining_energy_wh=vehicle.usable_energy_wh, power_w=hover)]
        for start, end in route.legs():
            delta = [b - a for a, b in zip(start.position_enu_m, end.position_enu_m)]
            distance = math.hypot(*delta)
            if distance == 0:
                continue
            speed = min(
                end.target_speed_mps or DEFAULT_SPEED_MPS,
                vehicle.max_speed_mps or math.inf,
            )
            duration = distance / speed
            ground = [component / duration for component in delta]
            airspeed = math.hypot(
                ground[0] - wind_vector[0], ground[1] - wind_vector[1]
            )
            parasitic = 0.5 * rho * self.DRAG_COEFFICIENT * frontal_area * airspeed**3
            climb = max(weight * ground[2], 0.0) / self.CLIMB_EFFICIENCY
            power = hover + parasitic + climb
            elapsed += duration
            consumed += power * duration / 3600
            peak = max(peak, power)
            samples.append(
                BatterySample(
                    t_s=elapsed,
                    remaining_energy_wh=vehicle.usable_energy_wh - consumed,
                    power_w=power,
                )
            )
        battery = BatteryState(
            usable_energy_wh=vehicle.usable_energy_wh,
            consumed_energy_wh=consumed,
            peak_power_w=peak,
            samples=tuple(samples),
        )
        energy_error = MeasureError(kind="absolute_bound", value=consumed * self.RELATIVE_ERROR)
        return {
            "battery_state": battery,
            "measures": MeasureSet(
                measures=(
                    Measure(name="route_energy_wh", value=consumed, unit="Wh", error=energy_error),
                    Measure(
                        name="remaining_energy_wh",
                        value=battery.remaining_energy_wh,
                        unit="Wh",
                        error=energy_error,
                    ),
                    Measure(name="peak_power_w", value=peak, unit="W"),
                )
            ),
        }

    def _reserve(self, inputs: Mapping[str, BaseModel]) -> dict[str, BaseModel]:
        battery = inputs["battery_state"]
        deployment = inputs["deployment"]
        assert isinstance(battery, BatteryState)
        assert isinstance(deployment, DeploymentIR)
        reserve_fraction = next(
            (
                float(constraint.value)
                for constraint in deployment.constraints
                if constraint.category == "energy"
                and constraint.unit == "1"
                and isinstance(constraint.value, int | float)
            ),
            0.0,
        )
        remaining = battery.remaining_energy_wh
        return {
            "measures": _measures(
                landing_reserve_wh=remaining,
                reserve_breach=remaining < reserve_fraction * battery.usable_energy_wh,
                forced_landing=remaining <= 0,
            )
        }


class SweptVolumeClearance(ToolAdapter):
    """Samples the planned route and measures clearance to box obstacles."""

    SAMPLE_SPACING_M = 0.5

    manifest = ToolManifest(
        id="builtin.swept-volume",
        version="0.1.0",
        name="Swept-volume route clearance",
        description="Sampled distance from the vehicle's swept extent to box obstacles and ground.",
        provides=(
            CapabilityProvision(
                capability_id="geometry.route_clearance",
                measures=("minimum_clearance_m", "terrain_clearance_m", "collision"),
            ),
        ),
        airframes=_ALL_AIRFRAMES,
        fidelity=FidelityClass.GEOMETRIC,
        errors=(
            ErrorSpec(
                measure="minimum_clearance_m",
                kind=UncertaintyKind.ABSOLUTE_BOUND,
                value=SAMPLE_SPACING_M / 2,
                unit="m",
                basis="Half the route sampling spacing; excludes site survey error",
            ),
        ),
        runtime=RuntimeSpec(typical_runtime_s=0.05),
        cost=CostClass.LOW,
        execution_mode=ExecutionMode.IN_PROCESS,
        reproducibility=_REPRODUCIBLE,
    )

    def compute(
        self, capability_id: str, inputs: Mapping[str, BaseModel]
    ) -> Mapping[str, BaseModel]:
        route = inputs["route"]
        site = inputs["site_geometry"]
        vehicle = inputs["vehicle_envelope"]
        assert isinstance(route, CanonicalRoute)
        assert isinstance(site, SiteGeometry)
        assert isinstance(vehicle, VehicleEnvelope)
        points = [route.waypoints[0].position_enu_m]
        for start, end in route.legs():
            steps = max(
                1,
                math.ceil(
                    math.dist(start.position_enu_m, end.position_enu_m)
                    / self.SAMPLE_SPACING_M
                ),
            )
            points.extend(
                tuple(a + (b - a) * i / steps for a, b in zip(start.position_enu_m, end.position_enu_m))
                for i in range(1, steps + 1)
            )
        # Terrain clearance ignores samples on the pad during takeoff and landing.
        airborne = [
            point for point in points if point[2] - site.ground_up_m > vehicle.extent_m[2]
        ]
        obstacle = min(
            (
                box.distance_m(point) - vehicle.radius_m
                for point in points
                for box in site.obstacles
            ),
            default=None,
        )
        terrain = min(
            (point[2] - site.ground_up_m - vehicle.extent_m[2] / 2 for point in airborne),
            default=None,
        )
        error = MeasureError(kind="absolute_bound", value=self.SAMPLE_SPACING_M / 2)
        measures = []
        if obstacle is not None:
            measures.append(
                Measure(name="minimum_clearance_m", value=obstacle, unit="m", error=error)
            )
        if terrain is not None:
            measures.append(Measure(name="terrain_clearance_m", value=terrain, unit="m"))
        measures.append(Measure(name="collision", value=obstacle is not None and obstacle <= 0))
        return {"measures": MeasureSet(measures=tuple(measures))}


BUILTIN_TOOLS: tuple[ToolAdapter, ...] = (
    DeploymentSemantics(),
    MomentumEnergy(),
    SweptVolumeClearance(),
)
