from drone_sim.schema_mapping import Conversion, FieldMapping, MappingCache, TelemetryColumnMapping, apply_mapping
from drone_sim.schema_mapping import map_telemetry_row, reconstruct_mapped_deployment, route_from_coordinates, route_from_kml_summary
import json
from pathlib import Path


def test_unfamiliar_vendor_key_is_mapped_deterministically_with_anchor() -> None:
    document = {"AUW_g": 4200, "wind_kmh": 36}
    value, anchor = apply_mapping(document, FieldMapping(source_pointer="/AUW_g", canonical_path="/vehicle/mass_kg", conversion=Conversion.GRAMS_TO_KG))
    assert value == 4.2
    assert anchor == "/AUW_g"


def test_mapping_is_cached_by_schema_not_values() -> None:
    cache = MappingCache()
    mapping = FieldMapping(source_pointer="/AUW_g", canonical_path="/vehicle/mass_kg", conversion=Conversion.GRAMS_TO_KG)
    cache.put({"AUW_g": 1}, (mapping,))
    assert cache.get({"AUW_g": 999}) == (mapping,)


def test_mapping_cache_persists_by_schema_fingerprint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mapping = FieldMapping(source_pointer="/AUW_g", canonical_path="/vehicle/mass_kg", conversion=Conversion.GRAMS_TO_KG)
    cache = MappingCache()
    cache.put({"AUW_g": 1}, (mapping,))
    cache.save(tmp_path / "mappings.json")

    assert MappingCache.load(tmp_path / "mappings.json").get({"AUW_g": 5000}) == (mapping,)


def test_kml_coordinates_become_canonical_drone_route() -> None:
    route = route_from_coordinates(((151.0, -33.0, 20), (151.1, -33.1, 25)))
    assert route.points[0].position.latitude_deg == -33.0
    assert route.points[1].position.altitude_m == 25


def test_complete_kml_summary_and_telemetry_columns_map_deterministically() -> None:
    route = route_from_kml_summary({"format": "kml", "coordinate_count": 2, "sample_coordinates": [[151.0, -33.0, 60], [151.1, -33.1, 75]]}, altitude_reference="mean_sea_level")
    signals, anchors = map_telemetry_row(
        {"alt_ft": 100, "vbat": 24.2, "speed_kmh": 36},
        (
            TelemetryColumnMapping(source_column="alt_ft", canonical_signal="altitude_m", conversion=Conversion.FEET_TO_M),
            TelemetryColumnMapping(source_column="vbat", canonical_signal="battery_voltage_v"),
            TelemetryColumnMapping(source_column="speed_kmh", canonical_signal="groundspeed_mps", conversion=Conversion.KMH_TO_MPS),
        ),
    )
    assert route.points[0].position.altitude_reference == "mean_sea_level"
    assert signals == {"altitude_m": 30.48, "battery_voltage_v": 24.2, "groundspeed_mps": 10.0}
    assert anchors["groundspeed_mps"] == "speed_kmh"


def test_unfamiliar_keys_and_kml_only_route_reconstruct_ready_ir() -> None:
    canonical = json.loads(Path("examples/demo_deployment.json").read_text())
    vendor = {
        "op_id": canonical["deployment_id"], "aircraft_blob": canonical["vehicle"],
        "payload_blob": canonical["payloads"], "job": {key: value for key, value in canonical["mission"].items() if key != "route"},
        "place": canonical["site"], "wx": canonical["conditions"], "fc": canonical["autonomy"],
        "limits": canonical["constraints"], "accept": canonical["success_criteria"],
        "logs": canonical["telemetry"], "raw": canonical["raw_data"], "models_blob": canonical["models"],
    }
    names = {"op_id": "deployment_id", "aircraft_blob": "vehicle", "payload_blob": "payloads", "job": "mission", "place": "site", "wx": "conditions", "fc": "autonomy", "limits": "constraints", "accept": "success_criteria", "logs": "telemetry", "raw": "raw_data", "models_blob": "models"}
    mappings = tuple(FieldMapping(source_pointer=f"/{source}", canonical_path=f"/{target}") for source, target in names.items())
    route = route_from_coordinates(tuple((point["position"]["longitude_deg"], point["position"]["latitude_deg"], point["position"]["altitude_m"]) for point in canonical["mission"]["route"]["points"]))

    deployment, anchors = reconstruct_mapped_deployment(vendor, mappings, route=route)

    assert deployment.vehicle.id == canonical["vehicle"]["id"]
    assert len(deployment.mission.route.points) == len(canonical["mission"]["route"]["points"])
    assert anchors["/vehicle"] == "/aircraft_blob"
