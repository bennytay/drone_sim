"""Deterministic application of LLM-proposed mappings for unfamiliar drone exports."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from drone_sim.ir import DeploymentIR, GeoPoint, Route, RoutePoint


class Conversion(StrEnum):
    IDENTITY = "identity"
    GRAMS_TO_KG = "g_to_kg"
    KMH_TO_MPS = "kmh_to_mps"
    FEET_TO_M = "ft_to_m"


class FieldMapping(BaseModel):
    """A model may name source and canonical paths, never manufacture values."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_pointer: str = Field(pattern=r"^/")
    canonical_path: str = Field(pattern=r"^/")
    conversion: Conversion = Conversion.IDENTITY


class TelemetryColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_column: str = Field(min_length=1)
    canonical_signal: str = Field(pattern=r"^(altitude_m|battery_voltage_v|groundspeed_mps)$")
    conversion: Conversion = Conversion.IDENTITY


def schema_fingerprint(document: object) -> str:
    def shape(value: Any) -> Any:
        if isinstance(value, dict): return {key: shape(child) for key, child in sorted(value.items())}
        if isinstance(value, list): return [shape(value[0])] if value else []
        return type(value).__name__
    return hashlib.sha256(json.dumps(shape(document), sort_keys=True).encode()).hexdigest()


def _read(document: object, pointer: str) -> Any:
    value: Any = document
    for token in pointer.removeprefix("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def convert_value(value: Any, conversion: Conversion) -> Any:
    if conversion == Conversion.IDENTITY: return value
    if not isinstance(value, (int, float)): raise ValueError("unit conversion requires a numeric source value")
    if conversion == Conversion.GRAMS_TO_KG: return value / 1000
    if conversion == Conversion.KMH_TO_MPS: return value / 3.6
    if conversion == Conversion.FEET_TO_M: return value * 0.3048
    raise ValueError(f"unsupported conversion {conversion}")


def apply_mapping(document: object, mapping: FieldMapping) -> tuple[Any, str]:
    """Return converted value plus the exact source pointer for provenance."""
    return convert_value(_read(document, mapping.source_pointer), mapping.conversion), mapping.source_pointer


def apply_mappings(document: object, mappings: tuple[FieldMapping, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    anchors: dict[str, str] = {}
    for mapping in mappings:
        value, anchor = apply_mapping(document, mapping)
        current = values
        tokens = mapping.canonical_path.removeprefix("/").split("/")
        for token in tokens[:-1]:
            current = current.setdefault(token, {})
        current[tokens[-1]] = value
        anchors[mapping.canonical_path] = anchor
    return values, anchors


def reconstruct_mapped_deployment(document: object, mappings: tuple[FieldMapping, ...], *, route: Route | None = None) -> tuple[DeploymentIR, dict[str, str]]:
    values, anchors = apply_mappings(document, mappings)
    if route is not None:
        mission = values.setdefault("mission", {})
        mission["route"] = route.model_dump(mode="json")
        anchors["/mission/route"] = "KML coordinates"
    return DeploymentIR.model_validate(values), anchors


def route_from_coordinates(
    coordinates: tuple[tuple[float, float, float | None], ...], *, altitude_reference: str = "above_ground"
) -> Route:
    """Convert already-parsed KML/GeoJSON coordinates without model-authored geometry."""
    if len(coordinates) < 2: raise ValueError("a planned route requires at least two coordinates")
    return Route(points=tuple(RoutePoint(id=f"wp-{index+1:02d}", position=GeoPoint(latitude_deg=latitude, longitude_deg=longitude, altitude_m=altitude or 0, altitude_reference=altitude_reference)) for index, (longitude, latitude, altitude) in enumerate(coordinates)))


def route_from_kml_summary(content: dict[str, Any], *, altitude_reference: str) -> Route:
    if content.get("format") != "kml":
        raise ValueError("route conversion requires a KML adapter summary")
    if content.get("coordinate_count") != len(content.get("sample_coordinates", ())):
        raise ValueError("truncated KML coordinates cannot become a canonical route")
    return route_from_coordinates(tuple(tuple(item) for item in content["sample_coordinates"]), altitude_reference=altitude_reference)


def map_telemetry_row(row: dict[str, Any], mappings: tuple[TelemetryColumnMapping, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    anchors: dict[str, str] = {}
    for mapping in mappings:
        if mapping.source_column not in row:
            raise KeyError(mapping.source_column)
        values[mapping.canonical_signal] = convert_value(row[mapping.source_column], mapping.conversion)
        anchors[mapping.canonical_signal] = mapping.source_column
    return values, anchors


class MappingCache(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mappings: dict[str, tuple[FieldMapping, ...]] = {}

    def put(self, document: object, mappings: tuple[FieldMapping, ...]) -> None:
        self.mappings[schema_fingerprint(document)] = mappings

    def get(self, document: object) -> tuple[FieldMapping, ...] | None:
        return self.mappings.get(schema_fingerprint(document))

    def save(self, path: "Path") -> None:
        from pathlib import Path
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(self.model_dump_json(indent=2) + "\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: "Path") -> "MappingCache":
        from pathlib import Path
        target = Path(path)
        return cls.model_validate_json(target.read_text()) if target.exists() else cls()
