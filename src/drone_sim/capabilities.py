"""Canonical drone capability ontology, independent of tools and simulators.

A capability names one causal transformation the planner may request: which
canonical data it consumes, which canonical data it produces, and which
observable measures it can emit. Fidelity, cost, and implementation belong to
registered providers, never to the capability itself.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.ir import StrictModel


class CapabilityDomain(StrEnum):
    WEATHER = "weather"
    GEOMETRY = "geometry"
    DYNAMICS = "dynamics"
    ENERGY = "energy"
    SENSING = "sensing"
    NAVIGATION = "navigation"
    COMMUNICATION = "communication"
    AUTONOMY = "autonomy"
    MISSION = "mission"
    EXTERNAL_ACTORS = "external_actors"
    RULES = "rules"
    UNCERTAINTY = "uncertainty"


class DataKind(StrEnum):
    """First-class canonical data exchanged between capabilities."""

    DEPLOYMENT = "deployment"
    ROUTE = "route"
    TRAJECTORY = "trajectory"
    SITE_GEOMETRY = "site_geometry"
    OPERATING_VOLUME = "operating_volume"
    WIND_FIELD = "wind_field"
    ATMOSPHERE = "atmosphere"
    VEHICLE_ENVELOPE = "vehicle_envelope"
    BATTERY_STATE = "battery_state"
    SENSOR_OBSERVATION = "sensor_observation"
    DETECTION = "detection"
    LOCALIZATION_ESTIMATE = "localization_estimate"
    LINK_STATE = "link_state"
    TRAFFIC = "traffic"
    CONDITION_SAMPLES = "condition_samples"
    CONSTRAINT_VIOLATION = "constraint_violation"
    MISSION_OUTCOME = "mission_outcome"
    MEASURE = "measure"


class CapabilityKind(StrEnum):
    ATOMIC = "atomic"
    COMPOSITE = "composite"


class Port(StrictModel):
    """One named, typed input or output of a capability."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: DataKind


_CAPABILITY_ID = r"^[a-z][a-z_]*\.[a-z][a-z0-9_]*$"


class Capability(StrictModel):
    """A tool-independent unit of work that a hypothesis can require.

    Composite capabilities name the atomic mechanisms they couple. When
    ``closed_loop`` is true, those components exchange feedback within one
    time step and must be provided by a single provider or co-simulation;
    the planner cannot chain them as separate providers.
    """

    id: str = Field(pattern=_CAPABILITY_ID)
    domain: CapabilityDomain
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: CapabilityKind = CapabilityKind.ATOMIC
    inputs: tuple[Port, ...] = Field(min_length=1)
    outputs: tuple[Port, ...] = Field(min_length=1)
    measures: tuple[str, ...] = ()
    composed_of: tuple[str, ...] = ()
    closed_loop: bool = False

    @model_validator(mode="after")
    def consistent_structure(self) -> Self:
        if self.id.split(".", 1)[0] != self.domain.value:
            raise ValueError("capability ID must be prefixed by its domain")
        for ports in (self.inputs, self.outputs):
            names = [port.name for port in ports]
            if len(names) != len(set(names)):
                raise ValueError("port names must be unique within inputs or outputs")
        if self.kind == CapabilityKind.COMPOSITE and len(self.composed_of) < 2:
            raise ValueError("composite capabilities require at least two components")
        if self.kind == CapabilityKind.ATOMIC and (self.composed_of or self.closed_loop):
            raise ValueError("atomic capabilities cannot declare components")
        if len(self.measures) != len(set(self.measures)):
            raise ValueError("capability measures must be unique")
        if self.measures and DataKind.MEASURE not in self.output_kinds:
            raise ValueError("capabilities with measures must output a measure set")
        return self

    @property
    def input_kinds(self) -> frozenset[DataKind]:
        return frozenset(port.kind for port in self.inputs)

    @property
    def output_kinds(self) -> frozenset[DataKind]:
        return frozenset(port.kind for port in self.outputs)


VENDOR_TERMS = (
    "airsim",
    "ardupilot",
    "carla",
    "dji",
    "gazebo",
    "isaac",
    "mavlink",
    "matlab",
    "px4",
    "simulink",
    "unreal",
)
_VENDOR_PATTERN = re.compile(rf"\b({'|'.join(VENDOR_TERMS)})\b", re.IGNORECASE)


def _vendor_terms(text: str) -> set[str]:
    return {match.lower() for match in _VENDOR_PATTERN.findall(text.replace("_", " "))}


class CapabilityOntology(StrictModel):
    """Versioned catalog of canonical capabilities the planner may request."""

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    capabilities: tuple[Capability, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def closed_and_vendor_neutral(self) -> Self:
        by_id = {capability.id: capability for capability in self.capabilities}
        if len(by_id) != len(self.capabilities):
            raise ValueError("capability IDs must be unique")
        for capability in self.capabilities:
            vendors = _vendor_terms(
                " ".join((capability.id, capability.name, capability.description))
            )
            if vendors:
                raise ValueError(
                    f"capability {capability.id} names vendor tools: "
                    f"{', '.join(sorted(vendors))}"
                )
            unknown = set(capability.composed_of) - set(by_id)
            if unknown:
                raise ValueError(
                    f"capability {capability.id} composes unknown capabilities: "
                    f"{', '.join(sorted(unknown))}"
                )
            if capability.kind == CapabilityKind.COMPOSITE:
                composites = [
                    component
                    for component in capability.composed_of
                    if by_id[component].kind == CapabilityKind.COMPOSITE
                ]
                if composites:
                    raise ValueError(
                        f"capability {capability.id} must compose atomic capabilities"
                    )
        return self

    def get(self, capability_id: str) -> Capability:
        for capability in self.capabilities:
            if capability.id == capability_id:
                return capability
        raise KeyError(capability_id)

    def producers(self, kind: DataKind) -> tuple[Capability, ...]:
        return tuple(
            capability
            for capability in self.capabilities
            if kind in capability.output_kinds
        )

    def measuring(self, measure: str) -> tuple[Capability, ...]:
        return tuple(
            capability
            for capability in self.capabilities
            if measure in capability.measures
        )


class MechanismBinding(StrictModel):
    """Minimum capability set that can test one taxonomy mechanism."""

    mechanism_id: str = Field(min_length=1)
    required: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class MechanismCapabilityMap(StrictModel):
    """Expresses failure hypotheses as capability requirements, not tools."""

    ontology_version: str
    taxonomy_version: str
    bindings: tuple[MechanismBinding, ...] = Field(min_length=1)

    def binding(self, mechanism_id: str) -> MechanismBinding:
        for binding in self.bindings:
            if binding.mechanism_id == mechanism_id:
                return binding
        raise KeyError(mechanism_id)

    def validate_against(
        self, ontology: CapabilityOntology, taxonomy: FailureTaxonomy
    ) -> tuple[str, ...]:
        """Return every structural gap between bindings, ontology, and taxonomy.

        A binding is complete when its capabilities exist, their inputs can be
        satisfied from Deployment IR or another required capability, and their
        measures cover every observable outcome the mechanism declares.
        """

        problems: list[str] = []
        if ontology.version != self.ontology_version:
            problems.append("binding ontology version does not match")
        if taxonomy.version != self.taxonomy_version:
            problems.append("binding taxonomy version does not match")
        leaves = {leaf.id: leaf for leaf in taxonomy.leaves()}
        known = {capability.id for capability in ontology.capabilities}
        bound = [binding.mechanism_id for binding in self.bindings]
        if len(bound) != len(set(bound)):
            problems.append("mechanisms may only be bound once")
        for missing in sorted(set(leaves) - set(bound)):
            problems.append(f"{missing}: no capability binding")
        for binding in self.bindings:
            leaf = leaves.get(binding.mechanism_id)
            if leaf is None:
                problems.append(f"{binding.mechanism_id}: unknown taxonomy mechanism")
                continue
            unknown = set(binding.required) - known
            if unknown:
                problems.append(
                    f"{leaf.id}: unknown capabilities {', '.join(sorted(unknown))}"
                )
                continue
            capabilities = [ontology.get(item) for item in binding.required]
            produced = {DataKind.DEPLOYMENT}.union(
                *(capability.output_kinds for capability in capabilities)
            )
            for capability in capabilities:
                unmet = capability.input_kinds - produced
                if unmet:
                    problems.append(
                        f"{leaf.id}: {capability.id} inputs "
                        f"{', '.join(sorted(unmet))} are not produced"
                    )
            measured = {m for capability in capabilities for m in capability.measures}
            uncovered = set(leaf.observable_outcomes) - measured
            if uncovered:
                problems.append(
                    f"{leaf.id}: outcomes {', '.join(sorted(uncovered))} are unmeasured"
                )
        return tuple(problems)


def _port(name: str, kind: DataKind | None = None) -> Port:
    return Port(name=name, kind=kind or DataKind(name))


def _capability(
    identifier: str,
    name: str,
    description: str,
    inputs: tuple[str | tuple[str, DataKind], ...],
    outputs: tuple[str | tuple[str, DataKind], ...],
    measures: tuple[str, ...] = (),
    **composition: object,
) -> Capability:
    def ports(items: tuple[str | tuple[str, DataKind], ...]) -> tuple[Port, ...]:
        return tuple(
            _port(item) if isinstance(item, str) else _port(*item) for item in items
        )

    output_ports = ports(outputs)
    if measures and DataKind.MEASURE not in {port.kind for port in output_ports}:
        output_ports = (*output_ports, _port(*_MEASURES))
    return Capability(
        id=identifier,
        domain=CapabilityDomain(identifier.split(".", 1)[0]),
        name=name,
        description=description,
        inputs=ports(inputs),
        outputs=output_ports,
        measures=measures,
        **composition,
    )


_MEASURES = ("measures", DataKind.MEASURE)
_VIOLATIONS = ("violations", DataKind.CONSTRAINT_VIOLATION)

DEFAULT_CAPABILITY_ONTOLOGY = CapabilityOntology(
    version="0.2.0",
    capabilities=(
        _capability(
            "weather.wind_field",
            "Wind field estimation",
            "Estimate steady wind, gusts, and turbulence along the operating area.",
            ("deployment", "site_geometry"),
            ("wind_field",),
            ("wind_speed_mps", "gust_speed_mps", "turbulence_intensity"),
        ),
        _capability(
            "weather.atmosphere",
            "Atmospheric state",
            "Estimate temperature, density, precipitation, visibility, and light.",
            ("deployment",),
            ("atmosphere",),
            (
                "temperature_c",
                "air_density_kg_m3",
                "precipitation_mm_h",
                "visibility_m",
                "illuminance_lux",
            ),
        ),
        _capability(
            "geometry.route_projection",
            "Route projection",
            "Project the planned route into a canonical local frame with timing.",
            ("deployment",),
            ("route",),
            ("route_length_m", "route_duration_s", "route_heading_deg"),
        ),
        _capability(
            "geometry.site_model",
            "Site geometry",
            "Assemble obstacles, terrain, and landing zones from site evidence.",
            ("deployment",),
            ("site_geometry",),
            ("model_age_s", "terrain_elevation_m", "landing_zone_width_m"),
        ),
        _capability(
            "geometry.operating_volume",
            "Operating volume",
            "Assemble authorized, geofenced, contingency, and controlled volumes.",
            ("deployment",),
            ("operating_volume",),
        ),
        _capability(
            "geometry.route_clearance",
            "Nominal route clearance",
            "Measure swept-volume clearance of the planned route to site geometry.",
            ("route", "site_geometry", "vehicle_envelope"),
            (_MEASURES,),
            (
                "minimum_clearance_m",
                "terrain_clearance_m",
                "collision",
                "route_blocked",
            ),
        ),
        _capability(
            "geometry.trajectory_clearance",
            "Flown trajectory clearance",
            "Measure clearance of a flown or perturbed trajectory to site geometry.",
            ("trajectory", "site_geometry", "vehicle_envelope"),
            (_MEASURES,),
            (
                "minimum_clearance_m",
                "obstacle_clearance_m",
                "clearance_breach",
                "collision",
                "obstacle_contact",
                "touchdown_error_m",
            ),
        ),
        _capability(
            "geometry.containment",
            "Volume containment",
            "Check a route or trajectory against authorized and geofenced volumes.",
            ("trajectory", "operating_volume"),
            (_VIOLATIONS,),
            (
                "airspace_breach",
                "geofence_breach",
                "altitude_breach_m",
                "unauthorized_segment_count",
                "containment_breach",
                "uncontrolled_exposure_s",
            ),
        ),
        _capability(
            "geometry.sky_visibility",
            "Sky and line-of-sight visibility",
            "Compute sky-view and line-of-sight obstruction along a route.",
            ("route", "site_geometry"),
            (_MEASURES,),
            ("satellite_visibility", "obstruction_depth_m", "multipath_bias_m"),
        ),
        _capability(
            "dynamics.vehicle_envelope",
            "Vehicle operating envelope",
            "Assemble mass, loading, and demonstrated limits of the configured drone.",
            ("deployment",),
            ("vehicle_envelope",),
            ("takeoff_mass_kg", "mass_margin_kg", "takeoff_rejected"),
        ),
        _capability(
            "dynamics.performance_margin",
            "Performance margin",
            "Estimate thrust, climb, and control margin for loading and atmosphere.",
            ("vehicle_envelope", "atmosphere", "wind_field"),
            (_MEASURES,),
            (
                "thrust_margin",
                "climb_rate_mps",
                "control_margin",
                "control_saturation",
                "takeoff_failure",
            ),
        ),
        _capability(
            "dynamics.trajectory_response",
            "Trajectory response",
            "Predict the flown trajectory of the vehicle tracking a route under wind.",
            ("route", "vehicle_envelope", "wind_field", "atmosphere"),
            ("trajectory", _MEASURES),
            (
                "position_error_m",
                "attitude_error_deg",
                "tracking_error_m",
                "route_deviation_m",
                "oscillation",
                "control_saturation",
            ),
        ),
        _capability(
            "energy.route_demand",
            "Route energy demand",
            "Integrate power demand over the route under loading and wind.",
            ("route", "vehicle_envelope", "wind_field", "atmosphere"),
            ("battery_state",),
            ("route_energy_wh", "remaining_energy_wh", "peak_power_w"),
        ),
        _capability(
            "energy.battery_response",
            "Battery response",
            "Apply temperature derating, voltage sag, and power limits to demand.",
            (("demand", DataKind.BATTERY_STATE), "atmosphere"),
            ("battery_state",),
            ("capacity_derating", "voltage_sag_v", "power_limit"),
        ),
        _capability(
            "energy.reserve_assessment",
            "Reserve assessment",
            "Compare remaining and contingency energy with required reserves.",
            ("battery_state", "deployment"),
            (_MEASURES,),
            (
                "reserve_breach",
                "forced_landing",
                "landing_reserve_wh",
                "alternate_unreachable",
                "mission_abort",
            ),
        ),
        _capability(
            "sensing.observation_synthesis",
            "Sensor observation synthesis",
            "Predict payload and navigation sensor observations along a trajectory.",
            ("trajectory", "site_geometry", "atmosphere", "deployment"),
            ("sensor_observation",),
            (
                "image_quality",
                "ground_sample_distance",
                "motion_blur_px",
                "valid_frame_fraction",
                "sensor_occlusion",
                "invalid_measurement_fraction",
                "payload_quality_loss",
            ),
        ),
        _capability(
            "sensing.detection",
            "Detection and measurement",
            "Apply the deployed perception task to observations.",
            ("sensor_observation",),
            ("detection", _MEASURES),
            (
                "detection_recall",
                "false_detection_rate",
                "measurement_error",
                "coverage_gap",
                "inspection_incomplete",
            ),
        ),
        _capability(
            "navigation.absolute_positioning",
            "Absolute positioning quality",
            "Estimate satellite positioning and heading error along a trajectory.",
            ("trajectory", "site_geometry", "deployment"),
            ("localization_estimate",),
            (
                "position_error_m",
                "heading_error_deg",
                "localization_error_m",
                "mode_degradation",
            ),
        ),
        _capability(
            "navigation.relative_localization",
            "Relative localization quality",
            "Estimate feature-based localization drift and tracking loss.",
            ("sensor_observation", "trajectory"),
            ("localization_estimate",),
            (
                "localization_covariance",
                "localization_error_m",
                "map_misalignment_m",
                "tracking_loss",
            ),
        ),
        _capability(
            "communication.link_budget",
            "Link budget",
            "Estimate command, telemetry, and payload link quality along a trajectory.",
            ("trajectory", "site_geometry", "deployment"),
            ("link_state",),
            (
                "path_loss_db",
                "link_margin_db",
                "packet_loss",
                "link_outage_s",
                "latency_ms",
                "telemetry_gap",
            ),
        ),
        _capability(
            "communication.stream_capacity",
            "Payload stream capacity",
            "Compare required payload bitrate and latency with link capacity.",
            ("link_state", "deployment"),
            (_MEASURES,),
            ("dropped_frame_fraction", "delivery_latency_ms", "mission_criterion_breach"),
        ),
        _capability(
            "autonomy.failsafe_response",
            "Failsafe response",
            "Predict the contingency trajectory triggered by link, navigation, or energy loss.",
            ("route", "deployment", "link_state"),
            ("trajectory", _MEASURES),
            ("failsafe_activation", "unsafe_landing", "go_around"),
        ),
        _capability(
            "autonomy.closed_loop_flight",
            "Closed-loop flight",
            "Execute the deployed autonomy with coupled dynamics, sensing, and navigation.",
            (
                "route",
                "vehicle_envelope",
                "wind_field",
                "atmosphere",
                "site_geometry",
                "deployment",
            ),
            ("trajectory", "sensor_observation", "mission_outcome", _MEASURES),
            (
                "position_error_m",
                "attitude_error_deg",
                "clearance_breach",
                "collision",
                "touchdown_error_m",
                "obstacle_contact",
                "go_around",
                "failsafe_activation",
                "tracking_loss",
                "avoidance_manoeuvre",
                "mission_abort",
                "unsafe_landing",
            ),
            kind=CapabilityKind.COMPOSITE,
            closed_loop=True,
            composed_of=(
                "dynamics.trajectory_response",
                "navigation.absolute_positioning",
                "sensing.observation_synthesis",
                "autonomy.failsafe_response",
            ),
        ),
        _capability(
            "mission.timing",
            "Mission timing",
            "Compare flown and task durations with the available operating window.",
            ("trajectory", "deployment"),
            ("mission_outcome",),
            ("completion_time_s", "missed_window", "incomplete_tasks"),
        ),
        _capability(
            "mission.action_sequence",
            "Action sequence",
            "Check waypoint actions, ordering, and dwell against route timing.",
            ("route", "deployment"),
            ("mission_outcome",),
            ("skipped_action", "route_deviation_m", "criterion_breach"),
        ),
        _capability(
            "external_actors.traffic_model",
            "External actor model",
            "Model plausible crewed aircraft, people, vehicles, wildlife, or temporary obstacles.",
            ("deployment",),
            ("traffic",),
            ("actor_arrival_rate", "wildlife_density"),
        ),
        _capability(
            "external_actors.encounter",
            "Encounter assessment",
            "Measure separation and required response between drone and external actors.",
            ("trajectory", "traffic"),
            (_MEASURES,),
            (
                "minimum_separation_m",
                "minimum_clearance_m",
                "avoidance_manoeuvre",
                "hold_duration_s",
                "route_blocked",
                "collision",
                "strike",
                "unsafe_landing",
                "mission_abort",
            ),
        ),
        _capability(
            "rules.operating_constraints",
            "Operating constraint check",
            "Evaluate declared operating constraints and site rules against the plan.",
            ("deployment", "route", "operating_volume"),
            (_VIOLATIONS,),
            ("rule_violation_count", "mission_cancelled", "unauthorized_segment_count"),
        ),
        _capability(
            "rules.success_criteria",
            "Success criteria check",
            "Evaluate mission outcomes against declared deployment success criteria.",
            ("mission_outcome", "deployment"),
            (_VIOLATIONS,),
            ("criterion_breach", "mission_criterion_breach"),
        ),
        _capability(
            "uncertainty.condition_sampling",
            "Condition sampling",
            "Sample plausible deployment conditions within evidence uncertainty.",
            ("deployment",),
            ("condition_samples",),
            ("sample_count",),
        ),
        _capability(
            "uncertainty.propagation",
            "Uncertainty propagation",
            "Propagate sampled conditions through a measure into a margin distribution.",
            ("condition_samples", _MEASURES),
            (_MEASURES,),
            ("margin_lower_bound", "exceedance_probability"),
        ),
    ),
)


def _bind(mechanism_id: str, rationale: str, *required: str) -> MechanismBinding:
    return MechanismBinding(
        mechanism_id=mechanism_id, required=required, rationale=rationale
    )


_ROUTE = ("geometry.route_projection",)
_FLIGHT = (
    "geometry.route_projection",
    "dynamics.vehicle_envelope",
    "weather.atmosphere",
    "geometry.site_model",
    "weather.wind_field",
)
_CLOSED_LOOP = (*_FLIGHT, "autonomy.closed_loop_flight")
_TRACKED = (*_FLIGHT, "dynamics.trajectory_response")
_ENERGY = (*_FLIGHT, "energy.route_demand")


DEFAULT_MECHANISM_CAPABILITIES = MechanismCapabilityMap(
    ontology_version=DEFAULT_CAPABILITY_ONTOLOGY.version,
    taxonomy_version=DEFAULT_FAILURE_TAXONOMY.version,
    bindings=(
        _bind(
            "environment_weather.wind.steady_limit",
            "Route-local wind loads the tracking response and energy reserve.",
            *_TRACKED,
            "energy.route_demand",
            "energy.reserve_assessment",
        ),
        _bind(
            "environment_weather.wind.gust_turbulence",
            "Transient upset depends on coupled control response near structures.",
            *_CLOSED_LOOP,
            "geometry.trajectory_clearance",
            "sensing.observation_synthesis",
        ),
        _bind(
            "environment_weather.visibility.degradation",
            "Contrast loss propagates through observations to perception and navigation.",
            *_TRACKED,
            "sensing.observation_synthesis",
            "sensing.detection",
            "navigation.relative_localization",
        ),
        _bind(
            "environment_weather.visibility.precipitation",
            "Precipitation affects thrust margin, sensor surfaces, and reserve.",
            *_TRACKED,
            "dynamics.performance_margin",
            "sensing.observation_synthesis",
            "energy.route_demand",
            "energy.reserve_assessment",
        ),
        _bind(
            "energy_battery.reserve.route_demand",
            "Integrated route demand is compared against usable reserve.",
            *_ENERGY,
            "energy.reserve_assessment",
        ),
        _bind(
            "energy_battery.reserve.temperature_derating",
            "Cold or hot cells derate capacity and limit peak power.",
            *_ENERGY,
            "energy.battery_response",
            "energy.reserve_assessment",
        ),
        _bind(
            "energy_battery.contingency.diversion",
            "Contingency legs must remain reachable with landing reserve.",
            *_ENERGY,
            "energy.reserve_assessment",
        ),
        _bind(
            "geometry_clearance.route.static_obstacle",
            "Flown position uncertainty reduces nominal obstacle clearance.",
            *_TRACKED,
            "geometry.route_clearance",
            "geometry.trajectory_clearance",
        ),
        _bind(
            "geometry_clearance.route.vertical_reference",
            "Altitude datum errors change terrain and airspace clearance.",
            *_FLIGHT,
            "geometry.route_clearance",
            "geometry.operating_volume",
            "dynamics.trajectory_response",
            "geometry.containment",
        ),
        _bind(
            "geometry_clearance.terminal.landing_zone",
            "Terminal approach geometry depends on closed-loop touchdown dispersion.",
            *_CLOSED_LOOP,
            "geometry.trajectory_clearance",
        ),
        _bind(
            "vehicle_operating_envelope.loading.mass",
            "Configured takeoff mass is compared with the declared limit.",
            "dynamics.vehicle_envelope",
        ),
        _bind(
            "vehicle_operating_envelope.loading.balance_drag",
            "Payload balance and drag reduce control margin while tracking.",
            *_TRACKED,
            "dynamics.performance_margin",
        ),
        _bind(
            "vehicle_operating_envelope.performance.density_altitude",
            "Air density and loading bound available thrust and climb.",
            "dynamics.vehicle_envelope",
            "weather.atmosphere",
            "geometry.site_model",
            "weather.wind_field",
            "dynamics.performance_margin",
        ),
        _bind(
            "navigation_localization.absolute.gnss_occlusion",
            "Sky obstruction degrades positioning, which erodes flown clearance.",
            *_TRACKED,
            "geometry.sky_visibility",
            "navigation.absolute_positioning",
            "geometry.trajectory_clearance",
        ),
        _bind(
            "navigation_localization.absolute.interference",
            "Site interference exposure degrades heading and triggers failsafes.",
            *_TRACKED,
            "navigation.absolute_positioning",
            "communication.link_budget",
            "autonomy.failsafe_response",
        ),
        _bind(
            "navigation_localization.relative.feature_poor",
            "Sparse or repetitive features degrade relative localization.",
            *_TRACKED,
            "sensing.observation_synthesis",
            "navigation.relative_localization",
        ),
        _bind(
            "perception_sensing.observability.range_resolution",
            "Standoff and motion determine resolution available to the task.",
            *_TRACKED,
            "sensing.observation_synthesis",
            "sensing.detection",
        ),
        _bind(
            "perception_sensing.observability.material",
            "Surface properties and incidence affect measurement validity.",
            *_TRACKED,
            "sensing.observation_synthesis",
            "sensing.detection",
        ),
        _bind(
            "perception_sensing.integrity.occlusion_contamination",
            "Occlusion or contamination reduces valid frames and task recall.",
            *_TRACKED,
            "sensing.observation_synthesis",
            "sensing.detection",
            "energy.route_demand",
            "energy.reserve_assessment",
        ),
        _bind(
            "communication.link.line_of_sight",
            "Obstructed paths reduce link margin and trigger lost-link behavior.",
            *_TRACKED,
            "geometry.sky_visibility",
            "communication.link_budget",
            "autonomy.failsafe_response",
        ),
        _bind(
            "communication.link.interference",
            "Channel interference increases latency, loss, and telemetry gaps.",
            *_TRACKED,
            "communication.link_budget",
        ),
        _bind(
            "communication.capacity.payload_stream",
            "Required payload bitrate must fit the available link capacity.",
            *_TRACKED,
            "communication.link_budget",
            "communication.stream_capacity",
        ),
        _bind(
            "mission_execution.plan.timing",
            "Flown duration and task time must fit the operating window.",
            *_TRACKED,
            "mission.timing",
        ),
        _bind(
            "mission_execution.plan.action_sequence",
            "Waypoint actions must execute in order at planned speeds.",
            *_ROUTE,
            "mission.action_sequence",
        ),
        _bind(
            "mission_execution.contingency.failsafe",
            "Contingency trajectories must remain clear and contained.",
            *_TRACKED,
            "communication.link_budget",
            "autonomy.failsafe_response",
            "geometry.trajectory_clearance",
            "geometry.operating_volume",
            "geometry.containment",
        ),
        _bind(
            "operational_site_regulatory.authorization.airspace",
            "Flown volume must remain within authorized airspace and times.",
            *_TRACKED,
            "geometry.operating_volume",
            "geometry.containment",
        ),
        _bind(
            "operational_site_regulatory.authorization.site_rule",
            "Declared site rules are evaluated deterministically against the plan.",
            *_ROUTE,
            "geometry.operating_volume",
            "rules.operating_constraints",
        ),
        _bind(
            "operational_site_regulatory.ground_risk.containment",
            "Flight and contingency volumes must stay within controlled areas.",
            *_TRACKED,
            "geometry.operating_volume",
            "geometry.containment",
        ),
        _bind(
            "deployment_external_actors.traffic.aircraft",
            "Separation from crewed traffic depends on flown trajectory and response.",
            *_TRACKED,
            "external_actors.traffic_model",
            "external_actors.encounter",
        ),
        _bind(
            "deployment_external_actors.traffic.ground",
            "People and vehicles entering controlled areas force holds or diversions.",
            *_TRACKED,
            "external_actors.traffic_model",
            "external_actors.encounter",
        ),
        _bind(
            "deployment_external_actors.dynamic_site.temporary_obstacle",
            "Obstacles absent from the site model can block the planned route.",
            *_TRACKED,
            "geometry.route_clearance",
            "external_actors.traffic_model",
            "external_actors.encounter",
        ),
        _bind(
            "deployment_external_actors.dynamic_site.wildlife",
            "Seasonal wildlife encounters require avoidance or abort.",
            *_TRACKED,
            "external_actors.traffic_model",
            "external_actors.encounter",
        ),
    ),
)
