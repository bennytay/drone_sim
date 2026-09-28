"""Versioned last-mile failure taxonomy for known-working drones."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from drone_sim.ir import StrictModel


class FailureDomain(StrEnum):
    ENVIRONMENT = "environment_weather"
    ENERGY = "energy_battery"
    GEOMETRY = "geometry_clearance"
    VEHICLE_ENVELOPE = "vehicle_operating_envelope"
    NAVIGATION = "navigation_localization"
    PERCEPTION = "perception_sensing"
    COMMUNICATION = "communication"
    MISSION = "mission_execution"
    OPERATIONS = "operational_site_regulatory"
    EXTERNAL_ACTORS = "deployment_external_actors"


class TaxonomyNode(StrictModel):
    """One branch or testable leaf in the drone fault tree."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    children: tuple[TaxonomyNode, ...] = ()
    causal_variables: tuple[str, ...] = ()
    observable_outcomes: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    deployment_tags: tuple[str, ...] = ("common",)

    @model_validator(mode="after")
    def branch_or_testable_leaf(self) -> Self:
        if self.children and (self.causal_variables or self.observable_outcomes):
            raise ValueError("branch nodes cannot define leaf test semantics")
        if not self.children and not (
            self.causal_variables and self.observable_outcomes and self.context_paths
        ):
            raise ValueError(
                "leaf nodes require causal variables, observable outcomes, and context paths"
            )
        return self

    def leaves(self) -> tuple[TaxonomyNode, ...]:
        if not self.children:
            return (self,)
        return tuple(leaf for child in self.children for leaf in child.leaves())


class FailureCategory(StrictModel):
    domain: FailureDomain
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    branches: tuple[TaxonomyNode, ...] = Field(min_length=1)

    def leaves(self) -> tuple[TaxonomyNode, ...]:
        return tuple(leaf for branch in self.branches for leaf in branch.leaves())


class FailureTaxonomy(StrictModel):
    """Canonical failure knowledge, not an assertion that every branch applies."""

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    product_scope: str = "known-working drone deployment readiness"
    categories: tuple[FailureCategory, ...] = Field(min_length=1)
    excluded_upstream_failures: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_and_unique(self) -> Self:
        domains = [category.domain for category in self.categories]
        if set(domains) != set(FailureDomain) or len(domains) != len(set(domains)):
            raise ValueError("taxonomy must contain each failure domain exactly once")
        identifiers = [
            leaf.id for category in self.categories for leaf in category.leaves()
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("taxonomy node IDs must be globally unique")
        return self

    def category(self, domain: FailureDomain) -> FailureCategory:
        return next(
            category for category in self.categories if category.domain == domain
        )

    def leaves(self) -> tuple[TaxonomyNode, ...]:
        return tuple(leaf for category in self.categories for leaf in category.leaves())


def _leaf(
    identifier: str,
    name: str,
    description: str,
    variables: tuple[str, ...],
    outcomes: tuple[str, ...],
    paths: tuple[str, ...],
    *tags: str,
) -> TaxonomyNode:
    return TaxonomyNode(
        id=identifier,
        name=name,
        description=description,
        causal_variables=variables,
        observable_outcomes=outcomes,
        context_paths=paths,
        deployment_tags=tags or ("common",),
    )


def _branch(identifier: str, name: str, *children: TaxonomyNode) -> TaxonomyNode:
    return TaxonomyNode(
        id=identifier,
        name=name,
        description=f"Groups {name.lower()} mechanisms.",
        children=children,
    )


DEFAULT_FAILURE_TAXONOMY = FailureTaxonomy(
    version="0.1.0",
    excluded_upstream_failures=(
        "basic airframe design defects unrelated to deployment conditions",
        "unfinished flight-control or autonomy development",
        "manufacturing defects not indicated by deployment evidence",
        "generic software correctness testing without a deployment trigger",
        "pilot training and certification as a substitute for deployment verification",
    ),
    categories=(
        FailureCategory(
            domain=FailureDomain.ENVIRONMENT,
            name="Environment and weather",
            description="Atmospheric conditions that alter flight, sensing, or exposure.",
            branches=(
                _branch(
                    "environment_weather.wind",
                    "Wind interaction",
                    _leaf(
                        "environment_weather.wind.steady_limit",
                        "Steady wind exceeds margin",
                        "Route-local wind demand exceeds the aircraft's demonstrated limit.",
                        ("wind_speed_mps", "wind_direction_deg", "route_heading_deg"),
                        ("position_error_m", "control_saturation", "mission_abort"),
                        (
                            "/conditions/wind_speed_mps",
                            "/vehicle/max_wind_speed_mps",
                            "/mission/route",
                        ),
                    ),
                    _leaf(
                        "environment_weather.wind.gust_turbulence",
                        "Gust or turbulence upset",
                        "Terrain or structures create transient disturbances beyond recovery margin.",
                        ("gust_speed_mps", "turbulence_intensity", "clearance_m"),
                        (
                            "attitude_error_deg",
                            "clearance_breach",
                            "payload_quality_loss",
                        ),
                        ("/site", "/mission/route", "/vehicle"),
                        "urban",
                        "infrastructure_inspection",
                    ),
                ),
                _branch(
                    "environment_weather.visibility",
                    "Visibility and precipitation",
                    _leaf(
                        "environment_weather.visibility.degradation",
                        "Visibility degradation",
                        "Fog, haze, glare, or low light removes contrast needed by the deployed sensing task.",
                        ("visibility_m", "illuminance_lux", "glare_angle_deg"),
                        ("detection_recall", "localization_error_m", "image_quality"),
                        ("/conditions/visibility_m", "/payloads", "/mission/objective"),
                        "mapping",
                        "inspection",
                    ),
                    _leaf(
                        "environment_weather.visibility.precipitation",
                        "Precipitation exposure",
                        "Rain, snow, or icing changes aerodynamics, sensor surfaces, or safe operating limits.",
                        ("precipitation_mm_h", "temperature_c", "exposure_s"),
                        ("thrust_margin", "sensor_occlusion", "mission_abort"),
                        ("/conditions", "/vehicle", "/payloads"),
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.ENERGY,
            name="Energy and battery",
            description="Deployment demand that consumes or constrains usable energy.",
            branches=(
                _branch(
                    "energy_battery.reserve",
                    "Usable reserve",
                    _leaf(
                        "energy_battery.reserve.route_demand",
                        "Route energy exceeds reserve",
                        "Distance, climb, payload, and wind leave insufficient landing reserve.",
                        ("route_energy_wh", "usable_energy_wh", "reserve_fraction"),
                        ("remaining_energy_wh", "reserve_breach", "forced_landing"),
                        (
                            "/mission/route",
                            "/vehicle/mass_kg",
                            "/payloads",
                            "/conditions",
                        ),
                    ),
                    _leaf(
                        "energy_battery.reserve.temperature_derating",
                        "Temperature derates battery",
                        "Site temperature reduces available capacity or power below mission demand.",
                        ("temperature_c", "capacity_derating", "peak_power_w"),
                        ("voltage_sag_v", "power_limit", "mission_abort"),
                        ("/conditions/temperature_c", "/vehicle", "/mission"),
                        "cold_weather",
                        "hot_weather",
                    ),
                ),
                _branch(
                    "energy_battery.contingency",
                    "Contingency energy",
                    _leaf(
                        "energy_battery.contingency.diversion",
                        "Diversion reserve inadequate",
                        "A plausible hold, go-around, or alternate landing consumes more than the protected contingency reserve.",
                        (
                            "diversion_distance_m",
                            "hold_duration_s",
                            "reserve_energy_wh",
                        ),
                        ("landing_reserve_wh", "alternate_unreachable"),
                        ("/mission", "/site", "/constraints"),
                        "bvlos",
                        "delivery",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.GEOMETRY,
            name="Geometry and clearance",
            description="Spatial incompatibility between aircraft, route, and site.",
            branches=(
                _branch(
                    "geometry_clearance.route",
                    "Route clearance",
                    _leaf(
                        "geometry_clearance.route.static_obstacle",
                        "Static obstacle clearance",
                        "Aircraft footprint and navigation uncertainty consume the planned obstacle margin.",
                        (
                            "nominal_clearance_m",
                            "vehicle_extent_m",
                            "position_uncertainty_m",
                        ),
                        ("minimum_clearance_m", "collision"),
                        ("/mission/route", "/vehicle/dimensions_m", "/site/artifacts"),
                        "urban",
                        "inspection",
                    ),
                    _leaf(
                        "geometry_clearance.route.vertical_reference",
                        "Altitude reference mismatch",
                        "Route and site elevations use incompatible vertical references.",
                        ("route_altitude_m", "terrain_elevation_m", "datum_offset_m"),
                        ("terrain_clearance_m", "airspace_breach"),
                        ("/mission/route", "/site/reference_point", "/constraints"),
                        "mapping",
                        "bvlos",
                    ),
                ),
                _branch(
                    "geometry_clearance.terminal",
                    "Takeoff and landing",
                    _leaf(
                        "geometry_clearance.terminal.landing_zone",
                        "Landing zone incompatible",
                        "Available landing geometry or approach corridor is too small or obstructed for the configured drone.",
                        (
                            "landing_zone_width_m",
                            "approach_slope_deg",
                            "vehicle_extent_m",
                        ),
                        ("touchdown_error_m", "obstacle_contact", "go_around"),
                        ("/site", "/vehicle/dimensions_m", "/mission"),
                        "delivery",
                        "remote_site",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.VEHICLE_ENVELOPE,
            name="Vehicle operating envelope",
            description="Deployment demand outside the known-working configuration envelope.",
            branches=(
                _branch(
                    "vehicle_operating_envelope.loading",
                    "Configuration loading",
                    _leaf(
                        "vehicle_operating_envelope.loading.mass",
                        "Takeoff mass margin",
                        "Deployment payload and consumables exceed the permitted or demonstrated mass.",
                        ("takeoff_mass_kg", "max_takeoff_mass_kg"),
                        ("mass_margin_kg", "takeoff_rejected"),
                        ("/vehicle", "/payloads"),
                    ),
                    _leaf(
                        "vehicle_operating_envelope.loading.balance_drag",
                        "Payload balance or drag",
                        "Payload placement or exposed area changes stability and control demand.",
                        ("center_of_mass_offset_m", "drag_area_m2", "airspeed_mps"),
                        ("control_margin", "tracking_error_m", "oscillation"),
                        ("/vehicle", "/payloads", "/mission"),
                        "delivery",
                        "inspection",
                    ),
                ),
                _branch(
                    "vehicle_operating_envelope.performance",
                    "Site performance",
                    _leaf(
                        "vehicle_operating_envelope.performance.density_altitude",
                        "Density-altitude performance",
                        "Elevation and temperature reduce available thrust below route demand.",
                        ("site_elevation_m", "temperature_c", "takeoff_mass_kg"),
                        ("thrust_margin", "climb_rate_mps", "takeoff_failure"),
                        (
                            "/site/reference_point",
                            "/conditions/temperature_c",
                            "/vehicle",
                        ),
                        "high_altitude",
                        "hot_weather",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.NAVIGATION,
            name="Navigation and localization",
            description="Site conditions that degrade position, heading, or route following.",
            branches=(
                _branch(
                    "navigation_localization.absolute",
                    "Absolute positioning",
                    _leaf(
                        "navigation_localization.absolute.gnss_occlusion",
                        "GNSS occlusion or multipath",
                        "Structures, terrain, or foliage reduce or bias satellite positioning.",
                        (
                            "satellite_visibility",
                            "multipath_bias_m",
                            "route_clearance_m",
                        ),
                        ("position_error_m", "mode_degradation", "clearance_breach"),
                        ("/site", "/mission/route", "/autonomy"),
                        "urban",
                        "infrastructure_inspection",
                    ),
                    _leaf(
                        "navigation_localization.absolute.interference",
                        "Navigation interference",
                        "Deployment-local RF interference disrupts GNSS or compass observations.",
                        (
                            "interference_level",
                            "magnetic_field_error",
                            "exposure_duration_s",
                        ),
                        (
                            "heading_error_deg",
                            "position_error_m",
                            "failsafe_activation",
                        ),
                        ("/site", "/autonomy", "/constraints"),
                        "industrial_site",
                        "urban",
                    ),
                ),
                _branch(
                    "navigation_localization.relative",
                    "Relative localization",
                    _leaf(
                        "navigation_localization.relative.feature_poor",
                        "Feature-poor localization",
                        "Repeated or low-texture surfaces leave visual or lidar localization underconstrained.",
                        ("feature_density", "scene_repetition", "speed_mps"),
                        (
                            "localization_covariance",
                            "map_misalignment_m",
                            "tracking_loss",
                        ),
                        ("/site/artifacts", "/payloads", "/mission"),
                        "warehouse",
                        "mapping",
                        "inspection",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.PERCEPTION,
            name="Perception and sensing",
            description="Deployment appearance or material properties that defeat sensing goals.",
            branches=(
                _branch(
                    "perception_sensing.observability",
                    "Target observability",
                    _leaf(
                        "perception_sensing.observability.range_resolution",
                        "Target below usable resolution",
                        "Standoff, motion, or optics leave the mission target too small or blurred.",
                        ("standoff_m", "ground_sample_distance", "motion_blur_px"),
                        (
                            "detection_recall",
                            "measurement_error",
                            "inspection_incomplete",
                        ),
                        ("/mission/route", "/payloads", "/success_criteria"),
                        "inspection",
                        "mapping",
                    ),
                    _leaf(
                        "perception_sensing.observability.material",
                        "Adverse surface response",
                        "Reflective, transparent, absorptive, or low-contrast materials invalidate sensor assumptions.",
                        (
                            "surface_reflectance",
                            "incidence_angle_deg",
                            "sensor_modality",
                        ),
                        (
                            "invalid_measurement_fraction",
                            "false_detection_rate",
                            "coverage_gap",
                        ),
                        ("/site/artifacts", "/payloads", "/mission/objective"),
                        "inspection",
                        "indoor",
                    ),
                ),
                _branch(
                    "perception_sensing.integrity",
                    "Sensor integrity",
                    _leaf(
                        "perception_sensing.integrity.occlusion_contamination",
                        "Sensor occlusion or contamination",
                        "Site dust, spray, glare, or payload geometry blocks a required field of view.",
                        ("occlusion_fraction", "contamination_rate", "sun_angle_deg"),
                        ("valid_frame_fraction", "detection_recall", "mission_abort"),
                        ("/conditions", "/payloads", "/vehicle"),
                        "industrial_site",
                        "coastal",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.COMMUNICATION,
            name="Communication",
            description="Deployment topology or spectrum that breaks required command and data links.",
            branches=(
                _branch(
                    "communication.link",
                    "Link availability",
                    _leaf(
                        "communication.link.line_of_sight",
                        "Control-link shadowing",
                        "Terrain or structures interrupt the required command-and-control link.",
                        ("path_loss_db", "obstruction_depth_m", "link_margin_db"),
                        ("packet_loss", "link_outage_s", "failsafe_activation"),
                        ("/mission/route", "/site/artifacts", "/constraints"),
                        "bvlos",
                        "urban",
                    ),
                    _leaf(
                        "communication.link.interference",
                        "Spectrum congestion",
                        "Deployment-local transmitters reduce link margin or corrupt command/data traffic.",
                        (
                            "interference_power_dbm",
                            "channel_occupancy",
                            "link_margin_db",
                        ),
                        ("latency_ms", "packet_loss", "telemetry_gap"),
                        ("/site", "/autonomy", "/constraints"),
                        "urban",
                        "industrial_site",
                    ),
                ),
                _branch(
                    "communication.capacity",
                    "Data capacity",
                    _leaf(
                        "communication.capacity.payload_stream",
                        "Payload stream exceeds link",
                        "Required sensor data rate exceeds available deployment bandwidth or latency budget.",
                        (
                            "required_bitrate_mbps",
                            "available_bitrate_mbps",
                            "latency_budget_ms",
                        ),
                        (
                            "dropped_frame_fraction",
                            "delivery_latency_ms",
                            "mission_criterion_breach",
                        ),
                        ("/payloads", "/success_criteria", "/mission"),
                        "inspection",
                        "mapping",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.MISSION,
            name="Mission execution",
            description="Deployment plan sequencing, timing, or contingency incompatibility.",
            branches=(
                _branch(
                    "mission_execution.plan",
                    "Plan feasibility",
                    _leaf(
                        "mission_execution.plan.timing",
                        "Mission timing infeasible",
                        "Route duration, task dwell, or time window cannot all be satisfied.",
                        ("route_duration_s", "task_duration_s", "available_window_s"),
                        ("completion_time_s", "missed_window", "incomplete_tasks"),
                        ("/mission", "/success_criteria", "/constraints"),
                    ),
                    _leaf(
                        "mission_execution.plan.action_sequence",
                        "Waypoint action conflict",
                        "A route action, speed, or ordering constraint conflicts with the mission objective.",
                        ("waypoint_order", "action_duration_s", "target_speed_mps"),
                        ("skipped_action", "route_deviation_m", "criterion_breach"),
                        ("/mission/route", "/success_criteria"),
                        "delivery",
                        "inspection",
                    ),
                ),
                _branch(
                    "mission_execution.contingency",
                    "Contingencies",
                    _leaf(
                        "mission_execution.contingency.failsafe",
                        "Failsafe unsuitable for site",
                        "Configured return, hover, or land behavior creates a new site-specific hazard.",
                        ("failsafe_mode", "return_altitude_m", "outage_location"),
                        ("obstacle_clearance_m", "geofence_breach", "unsafe_landing"),
                        ("/autonomy", "/site", "/constraints"),
                        "urban",
                        "bvlos",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.OPERATIONS,
            name="Operational, site, and regulatory constraints",
            description="Rules and site controls that make an otherwise flyable mission unacceptable.",
            branches=(
                _branch(
                    "operational_site_regulatory.authorization",
                    "Authorization",
                    _leaf(
                        "operational_site_regulatory.authorization.airspace",
                        "Airspace authorization conflict",
                        "Planned space, altitude, or time is outside granted operating authority.",
                        ("route_volume", "authorized_volume", "operation_time"),
                        ("unauthorized_segment_count", "altitude_breach_m"),
                        ("/mission/route", "/constraints"),
                        "urban",
                        "bvlos",
                    ),
                    _leaf(
                        "operational_site_regulatory.authorization.site_rule",
                        "Site rule conflict",
                        "Local access, exclusion, noise, or operating-hour rules conflict with execution.",
                        ("operation_time", "noise_limit", "exclusion_zone"),
                        ("rule_violation_count", "mission_cancelled"),
                        ("/site", "/constraints", "/mission"),
                    ),
                ),
                _branch(
                    "operational_site_regulatory.ground_risk",
                    "Ground risk controls",
                    _leaf(
                        "operational_site_regulatory.ground_risk.containment",
                        "Containment inadequate",
                        "Route or contingency footprints extend beyond the controlled ground area.",
                        ("flight_geography", "contingency_volume", "controlled_area"),
                        ("uncontrolled_exposure_s", "containment_breach"),
                        ("/mission/route", "/site", "/constraints"),
                        "urban",
                        "delivery",
                    ),
                ),
            ),
        ),
        FailureCategory(
            domain=FailureDomain.EXTERNAL_ACTORS,
            name="Deployment-specific external actors",
            description="Moving people, aircraft, animals, vehicles, or equipment that alter risk.",
            branches=(
                _branch(
                    "deployment_external_actors.traffic",
                    "Traffic interaction",
                    _leaf(
                        "deployment_external_actors.traffic.aircraft",
                        "Cooperative or non-cooperative aircraft",
                        "Plausible local air traffic intersects the route or contingency volume.",
                        ("traffic_trajectory", "drone_trajectory", "detection_range_m"),
                        (
                            "minimum_separation_m",
                            "avoidance_manoeuvre",
                            "mission_abort",
                        ),
                        ("/site", "/mission/route", "/constraints"),
                        "bvlos",
                        "urban",
                    ),
                    _leaf(
                        "deployment_external_actors.traffic.ground",
                        "Ground actor intrusion",
                        "People or vehicles enter takeoff, landing, or low-altitude operating areas.",
                        (
                            "actor_arrival_rate",
                            "controlled_area",
                            "detection_latency_s",
                        ),
                        ("minimum_separation_m", "hold_duration_s", "unsafe_landing"),
                        ("/site", "/mission", "/constraints"),
                        "delivery",
                        "inspection",
                    ),
                ),
                _branch(
                    "deployment_external_actors.dynamic_site",
                    "Dynamic site",
                    _leaf(
                        "deployment_external_actors.dynamic_site.temporary_obstacle",
                        "Temporary obstacle",
                        "Cranes, vessels, equipment, or vegetation occupy space absent from the static site model.",
                        ("obstacle_position", "obstacle_extent_m", "model_age_s"),
                        ("minimum_clearance_m", "route_blocked", "collision"),
                        ("/site/artifacts", "/mission/route", "/raw_data"),
                        "construction",
                        "industrial_site",
                    ),
                    _leaf(
                        "deployment_external_actors.dynamic_site.wildlife",
                        "Wildlife interaction",
                        "Site-specific birds or animals provoke conflict, avoidance, or mission interruption.",
                        ("wildlife_density", "encounter_distance_m", "season"),
                        ("avoidance_manoeuvre", "mission_abort", "strike"),
                        ("/site", "/conditions", "/mission"),
                        "coastal",
                        "rural",
                    ),
                ),
            ),
        ),
    ),
)
