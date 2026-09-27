import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from drone_sim.ir import DeploymentIR


FIXTURE = Path(__file__).parents[1] / "examples" / "demo_deployment.json"


def load_demo() -> dict:
    return json.loads(FIXTURE.read_text())


def test_realistic_demo_round_trips() -> None:
    deployment = DeploymentIR.model_validate(load_demo())

    assert deployment.schema_version == "0.1.0"
    assert deployment.vehicle.airframe == "multirotor"
    assert len(deployment.mission.route.points) == 2
    assert DeploymentIR.model_validate_json(deployment.model_dump_json()) == deployment


def test_schema_version_is_explicit() -> None:
    data = load_demo()
    data["schema_version"] = "0.2.0"

    with pytest.raises(ValidationError, match="schema_version"):
        DeploymentIR.model_validate(data)


def test_source_specific_fields_are_rejected() -> None:
    data = load_demo()
    data["vehicle"]["dji_product_code"] = "vendor-detail"

    with pytest.raises(ValidationError, match="dji_product_code"):
        DeploymentIR.model_validate(data)


def test_duplicate_artifact_ids_are_rejected() -> None:
    data = load_demo()
    data["telemetry"][0]["id"] = "site-mesh"

    with pytest.raises(ValidationError, match="artifact IDs must be unique"):
        DeploymentIR.model_validate(data)


def test_vehicle_cannot_exceed_takeoff_mass() -> None:
    data = load_demo()
    data["vehicle"]["mass_kg"] = 6.1

    with pytest.raises(ValidationError, match="max_takeoff_mass_kg"):
        DeploymentIR.model_validate(data)
