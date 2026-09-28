"""Generate reproducible, fictional drone deployment folders for QA.

The values are synthetic. Plausible ranges and file shapes are informed by:
- DJI enterprise aircraft specifications (mass, speed, wind envelopes)
- RFC 7946 GeoJSON coordinate ordering and WGS-84 semantics
- OGC KML 2.2
- PX4 ULog and ArduPilot DataFlash documentation
"""

from __future__ import annotations

import argparse
import binascii
import csv
import json
import math
import random
import shutil
import struct
import zlib
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCENARIOS = (
    ("rooftop-inspection", "Inspect rooftop HVAC equipment", "Sydney warehouse"),
    ("solar-farm-survey", "Capture thermal imagery of solar arrays", "Dubbo solar farm"),
    ("coastal-turbine", "Inspect turbine blades and nacelle", "Wollongong wind farm"),
    ("quarry-mapping", "Map stockpile volumes", "Lithgow quarry"),
    ("bridge-inspection", "Inspect bridge deck and piers", "Hawkesbury bridge"),
    ("night-search", "Search a defined area with thermal imaging", "Blue Mountains sector"),
)

LAYOUTS = ("clean", "messy", "conflicting", "incomplete", "split", "invalid_unit")

BASE_COORDINATES = (
    (-33.8688, 151.2093),
    (-32.2429, 148.6011),
    (-34.4278, 150.8931),
    (-33.4800, 150.1500),
    (-33.5520, 150.6800),
    (-33.7130, 150.3110),
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def route_points(
    rng: random.Random, latitude: float, longitude: float, count: int = 5
) -> list[dict[str, Any]]:
    points = []
    for index in range(count):
        points.append(
            {
                "id": f"wp-{index + 1:02d}",
                "position": {
                    "latitude_deg": round(latitude + index * 0.00012, 7),
                    "longitude_deg": round(longitude + index * 0.00014, 7),
                    "altitude_m": round(12 + index * 4 + rng.uniform(-1, 1), 1),
                    "altitude_reference": "above_ground",
                },
                "acceptance_radius_m": 2.0,
                "target_speed_mps": round(rng.uniform(3.0, 7.0), 1),
                "action": "capture_imagery" if index else "takeoff",
            }
        )
    return points


def canonical_deployment(
    rng: random.Random,
    index: int,
    scenario: tuple[str, str, str],
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    slug, objective, site_name = scenario
    vehicle_mass = round(rng.uniform(3.7, 6.7), 2)
    wind_limit = round(rng.uniform(10.0, 12.0), 1)
    points = route_points(rng, latitude, longitude)
    start = datetime(2026, 10, 5, 21, 0, tzinfo=UTC) + timedelta(days=index)
    return {
        "schema_version": "0.1.0",
        "deployment_id": f"synthetic-{index + 1:02d}-{slug}",
        "vehicle": {
            "id": f"fictional-uav-{rng.randint(100, 999)}",
            "airframe": "multirotor",
            "manufacturer": "Synthetic Aeroworks",
            "model": f"Verifier-{rng.choice(('M4', 'M6', 'X8'))}",
            "mass_kg": vehicle_mass,
            "max_takeoff_mass_kg": round(vehicle_mass + rng.uniform(1.0, 2.4), 2),
            "dimensions_m": [
                round(rng.uniform(0.55, 0.9), 2),
                round(rng.uniform(0.55, 0.9), 2),
                round(rng.uniform(0.25, 0.45), 2),
            ],
            "max_speed_mps": round(rng.uniform(15.0, 23.0), 1),
            "max_wind_speed_mps": wind_limit,
            "model_refs": [],
        },
        "payloads": [
            {
                "id": f"payload-{index + 1:02d}",
                "kind": rng.choice(("rgb_camera", "thermal_camera", "lidar")),
                "mass_kg": round(rng.uniform(0.35, 1.25), 2),
                "dimensions_m": [0.18, 0.14, 0.16],
                "model_refs": [],
            }
        ],
        "mission": {
            "name": slug.replace("-", " ").title(),
            "objective": objective,
            "route": {
                "points": points,
                "source": {
                    "id": f"route-{index + 1:02d}",
                    "uri": "route/flight.geojson",
                    "role": "route",
                    "media_type": "application/geo+json",
                },
            },
            "planned_start": start.isoformat().replace("+00:00", "Z"),
            "planned_duration_s": rng.randint(900, 2400),
        },
        "site": {
            "name": site_name,
            "reference_point": {
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "altitude_m": round(rng.uniform(5, 120), 1),
                "altitude_reference": "mean_sea_level",
            },
            "artifacts": [
                {
                    "id": f"site-model-{index + 1:02d}",
                    "uri": "site/site.obj",
                    "role": "site_model",
                    "media_type": "text/plain",
                }
            ],
        },
        "conditions": {
            "observed_at": (start - timedelta(minutes=30)).isoformat().replace(
                "+00:00", "Z"
            ),
            "temperature_c": round(rng.uniform(8, 31), 1),
            "wind_speed_mps": round(rng.uniform(2.0, 9.0), 1),
            "wind_direction_deg": rng.randrange(0, 360),
            "precipitation_mm_h": 0,
            "visibility_m": rng.choice((8000, 10000, 15000)),
            "artifacts": [],
        },
        "autonomy": {
            "mode": "supervised_autonomous",
            "controller": rng.choice(("PX4", "ArduPilot", "WaypointCore")),
            "version": f"{rng.randint(1, 3)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}",
            "config": None,
        },
        "constraints": [
            {
                "id": "steady-wind-limit",
                "category": "weather",
                "description": "Do not launch above the approved steady wind limit",
                "value": wind_limit,
                "unit": "m/s",
            },
            {
                "id": "minimum-reserve",
                "category": "energy",
                "description": "Minimum battery reserve at landing",
                "value": 25,
                "unit": "%",
            },
        ],
        "success_criteria": [
            {
                "id": "route-completion",
                "metric": "route_completion_ratio",
                "operator": "gte",
                "target": 0.98,
                "unit": "ratio",
            },
            {
                "id": "clearance",
                "metric": "obstacle_clearance_m",
                "operator": "gte",
                "target": 3.0,
                "unit": "m",
            },
        ],
        "telemetry": [
            {
                "id": f"reference-flight-{index + 1:02d}",
                "uri": "telemetry/reference.csv",
                "role": "telemetry",
                "media_type": "text/csv",
            }
        ],
        "raw_data": [
            {
                "id": f"site-image-{index + 1:02d}",
                "uri": "media/site.png",
                "role": "other",
                "media_type": "image/png",
            }
        ],
        "models": [],
    }


def alias_bundle(deployment: dict[str, Any]) -> dict[str, Any]:
    vehicle = deployment["vehicle"]
    mission = deployment["mission"]
    site = deployment["site"]
    autonomy = deployment["autonomy"]
    criteria = deployment["success_criteria"]
    return {
        "operator_export": {
            "operation_id": deployment["deployment_id"],
            "aircraft": {
                "aircraft_id": vehicle["id"],
                "type": vehicle["airframe"],
                "manufacturer": vehicle["manufacturer"],
                "model": vehicle["model"],
                "takeoff_mass_kg": vehicle["mass_kg"],
                "max_takeoff_mass_kg": vehicle["max_takeoff_mass_kg"],
                "size_m": vehicle["dimensions_m"],
                "max_speed_mps": vehicle["max_speed_mps"],
                "max_wind_speed_mps": vehicle["max_wind_speed_mps"],
                "model_refs": [],
            },
            "payload": deployment["payloads"],
            "flight_plan": {
                "title": mission["name"],
                "purpose": mission["objective"],
                "route": mission["route"],
                "planned_start": mission["planned_start"],
                "planned_duration_s": mission["planned_duration_s"],
            },
            "operating_site": site,
            "weather": deployment["conditions"],
            "flight_control": {
                "control_mode": autonomy["mode"],
                "flight_controller": autonomy["controller"],
                "controller_version": autonomy["version"],
                "config": None,
            },
            "operating_limits": deployment["constraints"],
            "acceptance_criteria": [
                {
                    "criterion_id": item["id"],
                    "measure": item["metric"],
                    "operator": item["operator"],
                    "threshold": item["target"],
                    "unit": item.get("unit"),
                }
                for item in criteria
            ],
            "telemetry": deployment["telemetry"],
            "raw_data": deployment["raw_data"],
            "models": deployment["models"],
        }
    }


def write_geojson(folder: Path, deployment: dict[str, Any]) -> None:
    coordinates = [
        [
            point["position"]["longitude_deg"],
            point["position"]["latitude_deg"],
            point["position"]["altitude_m"],
        ]
        for point in deployment["mission"]["route"]["points"]
    ]
    write_json(
        folder / "route" / "flight.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": deployment["deployment_id"],
                    "properties": {"altitude_reference": "above_ground"},
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            ],
        },
    )


def write_kml(folder: Path, deployment: dict[str, Any]) -> None:
    coordinates = " ".join(
        f'{point["position"]["longitude_deg"]},'
        f'{point["position"]["latitude_deg"]},'
        f'{point["position"]["altitude_m"]}'
        for point in deployment["mission"]["route"]["points"]
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
        f'<name>{deployment["deployment_id"]}</name><LineString>'
        f"<coordinates>{coordinates}</coordinates>"
        "</LineString></Placemark></Document></kml>\n"
    )
    path = folder / "route" / "alternate_route.kml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_telemetry(folder: Path, deployment: dict[str, Any], rng: random.Random) -> None:
    path = folder / "telemetry" / "reference.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ("timestamp_s", "latitude_deg", "longitude_deg", "altitude_m", "battery_v")
        )
        origin = deployment["mission"]["route"]["points"][0]["position"]
        for sample in range(180):
            writer.writerow(
                (
                    sample,
                    round(origin["latitude_deg"] + sample * 0.000002, 7),
                    round(origin["longitude_deg"] + sample * 0.000002, 7),
                    round(10 + 10 * math.sin(sample / 30), 2),
                    round(50.2 - sample * 0.018 + rng.uniform(-0.03, 0.03), 3),
                )
            )
    ulog = folder / "telemetry" / "reference.ulg"
    planned_start = datetime.fromisoformat(
        deployment["mission"]["planned_start"].replace("Z", "+00:00")
    )
    start_us = int(planned_start.timestamp() * 1_000_000)
    ulog.write_bytes(b"ULog\x01\x12\x35" + bytes([1]) + struct.pack("<Q", start_us))
    mcap = folder / "telemetry" / "sensors.mcap"
    mcap.write_bytes(b"\x89MCAP0\r\n" + bytes(rng.randrange(256) for _ in range(256)))


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(
        ">I", binascii.crc32(kind + data) & 0xFFFFFFFF
    )


def write_png(path: Path, width: int, height: int, rng: random.Random) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(
                (
                    (x * 7 + rng.randrange(20)) % 256,
                    (y * 9 + rng.randrange(20)) % 256,
                    ((x + y) * 5) % 256,
                )
            )
    data = b"\x89PNG\r\n\x1a\n"
    data += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += png_chunk(b"IDAT", zlib.compress(bytes(rows)))
    data += png_chunk(b"IEND", b"")
    path.write_bytes(data)


def write_site_model(folder: Path, rng: random.Random) -> None:
    path = folder / "site" / "site.obj"
    path.parent.mkdir(parents=True, exist_ok=True)
    height = round(rng.uniform(8, 35), 2)
    path.write_text(
        "# Synthetic site envelope\n"
        "v 0 0 0\n"
        f"v 20 0 {height}\n"
        f"v 20 20 {height}\n"
        f"v 0 20 {height}\n"
        "f 1 2 3 4\n",
        encoding="utf-8",
    )


def write_docx(folder: Path, deployment: dict[str, Any]) -> None:
    path = folder / "documents" / "operations_notes.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f'Deployment_ID: {deployment["deployment_id"]}. '
        f'Vehicle_ID: {deployment["vehicle"]["id"]}. '
        "Synthetic operations note; not approved for real flight."
    )
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("word/document.xml", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, xml)


def write_supporting_artifacts(
    folder: Path, deployment: dict[str, Any], rng: random.Random
) -> None:
    write_geojson(folder, deployment)
    write_kml(folder, deployment)
    write_telemetry(folder, deployment, rng)
    write_png(folder / "media" / "site.png", 64, 48, rng)
    write_site_model(folder, rng)
    write_docx(folder, deployment)
    notes = folder / "notes" / "README.txt"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "Synthetic QA fixture only. Do not use this folder to authorize a real flight.\n",
        encoding="utf-8",
    )


def emit_layout(
    folder: Path,
    deployment: dict[str, Any],
    layout: str,
    rng: random.Random,
) -> str:
    if layout == "clean":
        write_json(folder / "approved_current_deployment.json", deployment)
        expected = "ready"
    elif layout == "messy":
        write_json(folder / "random" / "stuff" / "final_export.json", alias_bundle(deployment))
        stale = alias_bundle(deployment)
        write_json(folder / "archive" / "backup_old.json", stale)
        expected = "ready"
    elif layout == "conflicting":
        write_json(folder / "approved_current_manifest.json", deployment)
        stale = json.loads(json.dumps(deployment))
        stale["vehicle"]["mass_kg"] = round(deployment["vehicle"]["mass_kg"] + 0.8, 2)
        stale["conditions"]["wind_speed_mps"] = round(
            min(stale["vehicle"]["max_wind_speed_mps"], stale["conditions"]["wind_speed_mps"] + 2.0),
            1,
        )
        write_json(folder / "archive" / "backup_old_manifest.json", stale)
        expected = "conflicting"
    elif layout == "incomplete":
        partial = {
            "operation_id": deployment["deployment_id"],
            "aircraft": alias_bundle(deployment)["operator_export"]["aircraft"],
            "operating_site": deployment["site"],
            "weather": deployment["conditions"],
        }
        write_json(folder / "handover" / "partial_notes.json", partial)
        expected = "incomplete"
    elif layout == "split":
        write_json(folder / "box-a" / "a.json", {"operation_id": deployment["deployment_id"]})
        write_json(folder / "box-b" / "b.json", {"aircraft": alias_bundle(deployment)["operator_export"]["aircraft"]})
        write_json(folder / "box-c" / "c.json", {"flight_plan": alias_bundle(deployment)["operator_export"]["flight_plan"]})
        write_json(folder / "box-d" / "d.json", {"operating_site": deployment["site"]})
        write_json(folder / "box-e" / "e.json", {"flight_control": alias_bundle(deployment)["operator_export"]["flight_control"]})
        write_json(folder / "box-f" / "f.json", {"acceptance_criteria": alias_bundle(deployment)["operator_export"]["acceptance_criteria"]})
        expected = "ready"
    elif layout == "invalid_unit":
        invalid = json.loads(json.dumps(deployment))
        invalid["constraints"][0]["unit"] = "mph"
        write_json(folder / "approved_current_deployment.json", invalid)
        expected = "invalid"
    else:
        raise ValueError(layout)
    write_supporting_artifacts(folder, deployment, rng)
    return expected


def generate(output: Path, seed: int, count: int, *, force: bool = False) -> None:
    if count < 1:
        raise ValueError("count must be positive")
    if output.exists() and any(output.iterdir()):
        if not force:
            raise ValueError(f"output directory is not empty: {output}")
        if not (output / "manifest.json").is_file():
            raise ValueError("refusing to replace an unrecognized output directory")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    manifest: list[dict[str, Any]] = []
    for index in range(count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        latitude, longitude = BASE_COORDINATES[index % len(BASE_COORDINATES)]
        layout = LAYOUTS[index % len(LAYOUTS)]
        folder = output / f"{index + 1:02d}_{scenario[0]}_{layout}"
        folder.mkdir(parents=True)
        deployment = canonical_deployment(
            rng, index, scenario, latitude, longitude
        )
        expected = emit_layout(folder, deployment, layout, rng)
        manifest.append(
            {
                "folder": folder.name,
                "layout": layout,
                "expected_readiness": expected,
                "deployment_id": deployment["deployment_id"],
                "evaluation_ground_truth": {
                    "expected_facts": [
                        "/vehicle/mass_kg",
                        "/vehicle/max_wind_speed_mps",
                        "/conditions/wind_speed_mps",
                    ],
                    "expected_mechanisms": [
                        "environment_weather.wind.steady_limit",
                        "vehicle_operating_envelope.loading.mass",
                    ],
                    "expected_ir_fields": [
                        "vehicle",
                        "mission",
                        "site",
                        "conditions",
                        "autonomy",
                    ],
                },
            }
        )
    write_json(output / "manifest.json", {"seed": seed, "deployments": manifest})
    (output / "SOURCES.md").write_text(
        "# Synthetic fixture research sources\n\n"
        "All deployments are fictional and unsafe for operational use. Values and file shapes "
        "were informed by these primary sources:\n\n"
        "- https://enterprise.dji.com/matrice-350-rtk/specs\n"
        "- https://enterprise.dji.com/matrice-30/specs\n"
        "- https://www.rfc-editor.org/rfc/rfc7946\n"
        "- https://docs.ogc.org/is/12-007r2/12-007r2.html\n"
        "- https://docs.px4.io/main/en/dev_log/ulog_file_format\n"
        "- https://ardupilot.org/dev/docs/code-overview-adding-a-new-log-message.html\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("examples/synthetic_deployments")
    )
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    generate(args.output, args.seed, args.count, force=args.force)


if __name__ == "__main__":
    main()
