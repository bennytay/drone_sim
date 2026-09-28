"""Deterministic application of LLM-proposed mappings for unfamiliar drone exports."""
from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from drone_sim.ir import GeoPoint, Route, RoutePoint


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


def _convert(value: Any, conversion: Conversion) -> Any:
    if conversion == Conversion.IDENTITY: return value
    if not isinstance(value, (int, float)): raise ValueError("unit conversion requires a numeric source value")
    if conversion == Conversion.GRAMS_TO_KG: return value / 1000
    if conversion == Conversion.KMH_TO_MPS: return value / 3.6
    if conversion == Conversion.FEET_TO_M: return value * 0.3048
    raise ValueError(f"unsupported conversion {conversion}")


def apply_mapping(document: object, mapping: FieldMapping) -> tuple[Any, str]:
    """Return converted value plus the exact source pointer for provenance."""
    return _convert(_read(document, mapping.source_pointer), mapping.conversion), mapping.source_pointer


def route_from_coordinates(
    coordinates: tuple[tuple[float, float, float | None], ...], *, altitude_reference: str = "above_ground"
) -> Route:
    """Convert already-parsed KML/GeoJSON coordinates without model-authored geometry."""
    if len(coordinates) < 2: raise ValueError("a planned route requires at least two coordinates")
    return Route(points=tuple(RoutePoint(id=f"wp-{index+1:02d}", position=GeoPoint(latitude_deg=latitude, longitude_deg=longitude, altitude_m=altitude or 0, altitude_reference=altitude_reference)) for index, (longitude, latitude, altitude) in enumerate(coordinates)))


class MappingCache(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mappings: dict[str, tuple[FieldMapping, ...]] = {}

    def put(self, document: object, mappings: tuple[FieldMapping, ...]) -> None:
        self.mappings[schema_fingerprint(document)] = mappings

    def get(self, document: object) -> tuple[FieldMapping, ...] | None:
        return self.mappings.get(schema_fingerprint(document))
