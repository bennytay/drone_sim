"""Canonical, vendor-neutral Deployment IR v0.1.

The IR describes deployment reality and intent. Source adapters own vendor
terminology and translate it into these canonical concepts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base type that rejects accidental, source-specific schema growth."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRole(StrEnum):
    DOCUMENT = "document"
    ROUTE = "route"
    TELEMETRY = "telemetry"
    SITE_MODEL = "site_model"
    CONTROLLER_CONFIG = "controller_config"
    VEHICLE_MODEL = "vehicle_model"
    PAYLOAD_MODEL = "payload_model"
    WEATHER = "weather"
    OTHER = "other"


class ArtifactRef(StrictModel):
    """Reference to bytes outside the IR; URIs may be relative to its bundle."""

    id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    role: ArtifactRole
    media_type: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class GeoPoint(StrictModel):
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    altitude_m: float
    altitude_reference: Literal["above_ground", "mean_sea_level", "ellipsoid"]


class RoutePoint(StrictModel):
    id: str = Field(min_length=1)
    position: GeoPoint
    acceptance_radius_m: float | None = Field(default=None, gt=0)
    target_speed_mps: float | None = Field(default=None, gt=0)
    action: str | None = None


class Route(StrictModel):
    points: tuple[RoutePoint, ...] = Field(min_length=2)
    source: ArtifactRef | None = None


class Vehicle(StrictModel):
    id: str = Field(min_length=1)
    airframe: Literal["multirotor", "fixed_wing", "vtol"]
    manufacturer: str | None = None
    model: str | None = None
    mass_kg: float = Field(gt=0)
    max_takeoff_mass_kg: float | None = Field(default=None, gt=0)
    dimensions_m: tuple[float, float, float]
    max_speed_mps: float | None = Field(default=None, gt=0)
    max_wind_speed_mps: float | None = Field(default=None, gt=0)
    model_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def mass_within_limit(self) -> "Vehicle":
        if self.max_takeoff_mass_kg and self.mass_kg > self.max_takeoff_mass_kg:
            raise ValueError("mass_kg cannot exceed max_takeoff_mass_kg")
        if any(value <= 0 for value in self.dimensions_m):
            raise ValueError("all dimensions_m values must be positive")
        return self


class Payload(StrictModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    mass_kg: float = Field(ge=0)
    dimensions_m: tuple[float, float, float] | None = None
    model_refs: tuple[ArtifactRef, ...] = ()


class Mission(StrictModel):
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    route: Route
    planned_start: datetime | None = None
    planned_duration_s: float | None = Field(default=None, gt=0)


class Site(StrictModel):
    name: str = Field(min_length=1)
    reference_point: GeoPoint | None = None
    artifacts: tuple[ArtifactRef, ...] = ()


class Conditions(StrictModel):
    observed_at: datetime | None = None
    temperature_c: float | None = None
    wind_speed_mps: float | None = Field(default=None, ge=0)
    wind_direction_deg: float | None = Field(default=None, ge=0, lt=360)
    precipitation_mm_h: float | None = Field(default=None, ge=0)
    visibility_m: float | None = Field(default=None, ge=0)
    artifacts: tuple[ArtifactRef, ...] = ()


class Autonomy(StrictModel):
    mode: Literal["manual", "assisted", "supervised_autonomous", "autonomous"]
    controller: str = Field(min_length=1)
    version: str | None = None
    config: ArtifactRef | None = None


class Constraint(StrictModel):
    id: str = Field(min_length=1)
    category: Literal["airspace", "geofence", "weather", "energy", "operations", "vehicle"]
    description: str = Field(min_length=1)
    value: float | str | bool | None = None
    unit: str | None = None


class SuccessCriterion(StrictModel):
    id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    operator: Literal["lt", "lte", "eq", "gte", "gt", "within"]
    target: float | str | bool
    unit: str | None = None


class ModelRef(StrictModel):
    id: str = Field(min_length=1)
    purpose: Literal["geometry", "dynamics", "sensor", "environment", "other"]
    artifact: ArtifactRef
    format: str | None = None


class DeploymentIR(StrictModel):
    """Minimum canonical description of one planned drone deployment."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    deployment_id: str = Field(min_length=1)
    vehicle: Vehicle
    payloads: tuple[Payload, ...] = ()
    mission: Mission
    site: Site
    conditions: Conditions | None = None
    autonomy: Autonomy
    constraints: tuple[Constraint, ...] = ()
    success_criteria: tuple[SuccessCriterion, ...] = Field(min_length=1)
    telemetry: tuple[ArtifactRef, ...] = ()
    raw_data: tuple[ArtifactRef, ...] = ()
    models: tuple[ModelRef, ...] = ()

    @model_validator(mode="after")
    def references_have_unique_ids(self) -> "DeploymentIR":
        refs = [*self.telemetry, *self.raw_data]
        refs.extend(self.site.artifacts)
        refs.extend(self.vehicle.model_refs)
        refs.extend(ref for payload in self.payloads for ref in payload.model_refs)
        refs.extend(model.artifact for model in self.models)
        if self.mission.route.source:
            refs.append(self.mission.route.source)
        if self.conditions:
            refs.extend(self.conditions.artifacts)
        if self.autonomy.config:
            refs.append(self.autonomy.config)
        ids = [ref.id for ref in refs]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact IDs must be unique across a deployment")
        return self
