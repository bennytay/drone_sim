import json
from pathlib import Path

import pytest

from drone_sim.context import ContextOrchestrator, DeterministicFileReader, DirectoryIndex, StateStore


def write_json(root: Path, name: str, value: object) -> None:
    (root / name).write_text(json.dumps(value))


def make_curated_folder(root: Path) -> None:
    root.mkdir()
    write_json(root, "deployment_manifest.json", {"deployment_id": "demo-001"})
    write_json(
        root,
        "aircraft_vehicle.json",
        {
            "vehicle": {
                "id": "uav-1",
                "airframe": "multirotor",
                "mass_kg": 2.4,
                "dimensions_m": [0.6, 0.6, 0.3],
            }
        },
    )
    write_json(root, "payload.json", {"payloads": []})
    write_json(
        root,
        "mission_route.json",
        {
            "mission": {
                "name": "Inspection",
                "objective": "Inspect the roof",
                "route": {
                    "points": [
                        {
                            "id": "a",
                            "position": {
                                "latitude_deg": -33.8,
                                "longitude_deg": 151.2,
                                "altitude_m": 10,
                                "altitude_reference": "above_ground",
                            },
                        },
                        {
                            "id": "b",
                            "position": {
                                "latitude_deg": -33.81,
                                "longitude_deg": 151.21,
                                "altitude_m": 20,
                                "altitude_reference": "above_ground",
                            },
                        },
                    ]
                },
            }
        },
    )
    write_json(root, "site_environment.json", {"site": {"name": "Warehouse"}})
    write_json(
        root,
        "autonomy_controller.json",
        {"autonomy": {"mode": "supervised_autonomous", "controller": "waypoint_follower"}},
    )
    write_json(
        root,
        "success_criteria.json",
        {
            "success_criteria": [
                {"id": "complete", "metric": "route_completion", "operator": "gte", "target": 0.98}
            ]
        },
    )
    (root / "irrelevant_notes.txt").write_text("Lunch order and meeting notes")


def test_orchestrator_reconstructs_ir_without_reading_irrelevant_file(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    make_curated_folder(source)
    state_path = tmp_path / "state" / "deployment.json"

    evidence, state = ContextOrchestrator(source, state_path).run()

    assert evidence is not None
    assert evidence.deployment.deployment_id == "demo-001"
    assert evidence.deployment.vehicle.airframe == "multirotor"
    assert evidence.deployment.mission.route.points[1].position.altitude_m == 20
    mass = evidence.fact("/vehicle/mass_kg")
    assert mass.selected.value == 2.4
    assert mass.selected.sources[0].source_path == "aircraft_vehicle.json"
    assert mass.selected.sources[0].locator == "/vehicle/mass_kg"
    assert mass.selected.uncertainty.confidence == "unknown"
    assert "irrelevant_notes.txt" not in state.inspected_paths
    assert state_path.exists()
    assert all(event.reason for event in state.trace)


def test_resume_does_not_reinspect_files(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    make_curated_folder(source)
    state_path = tmp_path / "deployment-state.json"
    orchestrator = ContextOrchestrator(source, state_path)

    first_deployment, first_state = orchestrator.run()
    second_deployment, second_state = orchestrator.run()

    assert first_deployment == second_deployment
    assert second_state.trace == first_state.trace


def test_single_canonical_manifest_is_only_read_once(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    source.mkdir()
    fixture = Path(__file__).parents[1] / "examples" / "demo_deployment.json"
    (source / "deployment.json").write_text(fixture.read_text())

    deployment, state = ContextOrchestrator(
        source, tmp_path / "manifest-state.json"
    ).run()

    assert deployment is not None
    assert deployment.deployment.deployment_id == "warehouse-roof-inspection-001"
    assert state.inspected_paths == {"deployment.json"}


def test_orchestrator_preserves_competing_candidate_values(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    make_curated_folder(source)
    write_json(
        source,
        "backup_aircraft_vehicle.json",
        {
            "vehicle": {
                "id": "uav-1",
                "airframe": "multirotor",
                "mass_kg": 2.7,
                "dimensions_m": [0.6, 0.6, 0.3],
            }
        },
    )

    evidence, state = ContextOrchestrator(
        source, tmp_path / "conflict-state.json"
    ).run()

    assert evidence is not None
    mass = evidence.fact("/vehicle/mass_kg")
    assert mass.selected.value == 2.4
    assert [candidate.value for candidate in mass.competing] == [2.7]
    assert len(state.candidates["vehicle"]) == 2


def test_state_must_be_outside_read_only_root(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    source.mkdir()

    with pytest.raises(ValueError, match="outside"):
        StateStore(source / "state.json", source)


def test_index_skips_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    source.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text("{}")
    (source / "linked.json").symlink_to(outside)

    assert DirectoryIndex.build(source).records == ()


def test_reader_enforces_size_limit(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    source.mkdir()
    (source / "large.txt").write_text("12345")

    with pytest.raises(ValueError, match="read limit"):
        DeterministicFileReader(source, max_file_bytes=4).parse("large.txt")


def test_reader_rejects_internal_symlink(tmp_path: Path) -> None:
    source = tmp_path / "deployment"
    source.mkdir()
    (source / "real.json").write_text("{}")
    (source / "linked.json").symlink_to(source / "real.json")

    with pytest.raises(ValueError, match="symlinks"):
        DeterministicFileReader(source).parse("linked.json")
