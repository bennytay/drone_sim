"""Reusable search, extraction, linking, and clarification primitives."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from drone_sim.adapters import ParsedSource
from drone_sim.ir import StrictModel


class DependencyTemplate(StrictModel):
    field: str = Field(min_length=1)
    query: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(min_length=1)
    preferred_suffixes: tuple[str, ...] = ()
    required: bool = False
    clarification_question: str = Field(min_length=1)


DEPENDENCY_TEMPLATES: tuple[DependencyTemplate, ...] = (
    DependencyTemplate(
        field="deployment_id",
        query="deployment operation identifier manifest overview",
        aliases=("deployment_id", "deployment_identifier", "operation_id"),
        preferred_suffixes=(".json", ".md", ".txt", ".pdf", ".docx"),
        required=True,
        clarification_question="What identifier should this drone deployment use?",
    ),
    DependencyTemplate(
        field="vehicle",
        query="vehicle aircraft drone uav airframe specification",
        aliases=("vehicle", "aircraft", "drone", "uav"),
        preferred_suffixes=(".json", ".pdf", ".docx", ".md"),
        required=True,
        clarification_question="Which drone and flight-ready configuration will be deployed?",
    ),
    DependencyTemplate(
        field="payloads",
        query="payload sensor camera cargo specification",
        aliases=("payloads", "payload", "sensors"),
        preferred_suffixes=(".json", ".pdf", ".docx"),
        clarification_question="Which payloads will be installed for this deployment?",
    ),
    DependencyTemplate(
        field="mission",
        query="mission route waypoints flight plan objective",
        aliases=("mission", "flight_plan", "operation_plan"),
        preferred_suffixes=(".json", ".geojson", ".kml", ".pdf", ".docx"),
        required=True,
        clarification_question="What mission objective and route should be verified?",
    ),
    DependencyTemplate(
        field="site",
        query="site environment location map mesh geometry",
        aliases=("site", "operating_site", "deployment_site"),
        preferred_suffixes=(".json", ".geojson", ".kml", ".glb", ".obj", ".ply"),
        required=True,
        clarification_question="At which operating site will the drone fly?",
    ),
    DependencyTemplate(
        field="conditions",
        query="conditions weather wind visibility temperature",
        aliases=("conditions", "weather", "forecast"),
        preferred_suffixes=(".json", ".csv", ".pdf"),
        clarification_question="What environmental conditions should the verification cover?",
    ),
    DependencyTemplate(
        field="autonomy",
        query="autonomy controller flight control configuration",
        aliases=("autonomy", "flight_control", "controller_configuration"),
        preferred_suffixes=(".json", ".params", ".txt", ".pdf"),
        required=True,
        clarification_question="Which autonomy mode and controller version will be used?",
    ),
    DependencyTemplate(
        field="constraints",
        query="constraints limits geofence airspace operations weather",
        aliases=("constraints", "operating_limits", "restrictions"),
        preferred_suffixes=(".json", ".pdf", ".docx", ".kml"),
        clarification_question="Which operational constraints apply to this deployment?",
    ),
    DependencyTemplate(
        field="success_criteria",
        query="success criteria acceptance threshold metrics",
        aliases=("success_criteria", "acceptance_criteria", "pass_criteria"),
        preferred_suffixes=(".json", ".pdf", ".docx", ".md"),
        required=True,
        clarification_question="What measurable outcomes define deployment success?",
    ),
    DependencyTemplate(
        field="telemetry",
        query="telemetry flight log historical data px4 ardupilot dji",
        aliases=("telemetry", "flight_logs", "reference_logs"),
        preferred_suffixes=(".ulg", ".tlog", ".bin", ".mcap", ".bag", ".csv"),
        clarification_question="Are representative flight logs available for this drone?",
    ),
    DependencyTemplate(
        field="raw_data",
        query="raw data imagery observations video",
        aliases=("raw_data", "imagery", "observations"),
        preferred_suffixes=(".png", ".jpg", ".jpeg", ".mp4", ".mov"),
        clarification_question="Is supporting imagery or video available?",
    ),
    DependencyTemplate(
        field="models",
        query="models dynamics geometry sensor environment mesh point cloud",
        aliases=("models", "simulation_models", "site_models"),
        preferred_suffixes=(".glb", ".gltf", ".obj", ".ply", ".pcd", ".las"),
        clarification_question="Are vehicle, sensor, or site models available?",
    ),
)

DEPENDENCY_BY_FIELD = {template.field: template for template in DEPENDENCY_TEMPLATES}


class EntityLink(StrictModel):
    entity_type: str = Field(min_length=1)
    canonical_value: str = Field(min_length=1)
    source_paths: tuple[str, ...] = Field(min_length=1)


class ClarificationRequest(StrictModel):
    field: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    searched_paths: tuple[str, ...] = ()


def extract_dependency(
    template: DependencyTemplate, content: Any
) -> tuple[Any, str, dict[str, str]] | None:
    """Find a canonical field by deterministic aliases at any object depth."""

    aliases = {_normalise_key(alias) for alias in template.aliases}

    def visit(value: Any, path: str) -> tuple[Any, str, dict[str, str]] | None:
        if not isinstance(value, dict):
            return None
        for key, child in value.items():
            if _normalise_key(str(key)) in aliases:
                source_location = f"{path}/{_escape_pointer(str(key))}"
                normalised, relative_locations = _normalise_with_locations(
                    template.field, child
                )
                return normalised, source_location, {
                    canonical: source_location + source
                    for canonical, source in relative_locations.items()
                }
        for key, child in value.items():
            found = visit(child, f"{path}/{_escape_pointer(str(key))}")
            if found:
                return found
        return None

    return visit(content, "")


def normalise_dependency_value(field: str, value: Any) -> Any:
    """Translate common drone-operator labels into canonical field names."""

    return _normalise_with_locations(field, value)[0]


def _normalise_with_locations(
    field: str, value: Any
) -> tuple[Any, dict[str, str]]:
    collection_fields = {
        "payloads",
        "constraints",
        "success_criteria",
        "telemetry",
        "raw_data",
        "models",
    }
    if field in collection_fields:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
    mappings: dict[str, dict[str, str]] = {
        "vehicle": {
            "vehicle_id": "id",
            "aircraft_id": "id",
            "drone_id": "id",
            "type": "airframe",
            "airframe_type": "airframe",
            "takeoff_mass_kg": "mass_kg",
            "weight_kg": "mass_kg",
            "size_m": "dimensions_m",
        },
        "mission": {
            "mission_name": "name",
            "title": "name",
            "purpose": "objective",
            "flight_route": "route",
        },
        "site": {"site_name": "name", "location_name": "name"},
        "autonomy": {
            "control_mode": "mode",
            "flight_controller": "controller",
            "controller_version": "version",
        },
        "conditions": {
            "wind_mps": "wind_speed_mps",
            "wind_direction": "wind_direction_deg",
            "temperature": "temperature_c",
            "visibility": "visibility_m",
        },
        "success_criteria": {
            "criterion_id": "id",
            "measure": "metric",
            "threshold": "target",
        },
    }
    mapping = mappings.get(field, {})

    locations: dict[str, str] = {}

    def rename(item: Any, canonical_path: str, source_path: str) -> Any:
        if isinstance(item, list):
            return [
                rename(
                    child,
                    f"{canonical_path}/{index}",
                    f"{source_path}/{index}",
                )
                for index, child in enumerate(item)
            ]
        if not isinstance(item, dict):
            locations[canonical_path] = source_path
            return item
        result = {}
        for key, child in item.items():
            canonical_key = mapping.get(_normalise_key(str(key)), str(key))
            result[canonical_key] = rename(
                child,
                f"{canonical_path}/{_escape_pointer(canonical_key)}",
                f"{source_path}/{_escape_pointer(str(key))}",
            )
        return result

    return rename(value, "", ""), locations


def evidence_priority(path: str, modified_at: datetime) -> tuple[int, float, str]:
    """Prefer approved/current sources, then recency, while retaining all rivals."""

    tokens = set(re.findall(r"[a-z0-9]+", Path(path).stem.lower()))
    score = 0
    if tokens & {"approved", "current", "final", "release", "signed"}:
        score += 2
    if tokens & {"archive", "archived", "backup", "old", "obsolete", "superseded"}:
        score -= 2
    return score, modified_at.timestamp(), path


_ENTITY_KEYS = {
    "deployment_id": "deployment",
    "deployment_identifier": "deployment",
    "vehicle_id": "vehicle",
    "aircraft_id": "vehicle",
    "drone_id": "vehicle",
    "site_id": "site",
    "site_name": "site",
}


def link_entities(sources: dict[str, ParsedSource]) -> tuple[EntityLink, ...]:
    mentions: dict[tuple[str, str], set[str]] = defaultdict(set)

    def visit(value: Any, source_path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                entity_type = _ENTITY_KEYS.get(_normalise_key(str(key)))
                if entity_type and isinstance(child, (str, int)):
                    canonical = re.sub(r"[^a-z0-9]+", "", str(child).lower())
                    if canonical:
                        mentions[(entity_type, canonical)].add(source_path)
                visit(child, source_path)
        elif isinstance(value, list):
            for child in value:
                visit(child, source_path)
        elif isinstance(value, str):
            for match in re.finditer(
                r"\b(deployment_id|deployment_identifier|vehicle_id|aircraft_id|"
                r"drone_id|site_id|site_name)\s*[:=]\s*([A-Za-z0-9._-]+)",
                value,
                flags=re.IGNORECASE,
            ):
                entity_type = _ENTITY_KEYS[_normalise_key(match.group(1))]
                canonical = re.sub(r"[^a-z0-9]+", "", match.group(2).lower())
                if canonical:
                    mentions[(entity_type, canonical)].add(source_path)

    for source_path, parsed in sources.items():
        visit(parsed.content, source_path)
    return tuple(
        EntityLink(
            entity_type=entity_type,
            canonical_value=canonical,
            source_paths=tuple(sorted(paths)),
        )
        for (entity_type, canonical), paths in sorted(mentions.items())
        if len(paths) > 1
    )


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
