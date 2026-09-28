import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from drone_sim.registry import (
    CostClass,
    FidelityClass,
    OperatingContext,
    RegionStatus,
    RegistrationError,
    ToolManifest,
    ToolRegistry,
)


MANIFESTS = Path(__file__).parents[1] / "examples" / "tool_manifests"


def load_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.load_directory(MANIFESTS)
    return registry


def manifest_data(name: str) -> dict:
    return json.loads((MANIFESTS / name).read_text())


def calm_multirotor(**variables: float) -> OperatingContext:
    return OperatingContext(
        airframe="multirotor",
        variables={"wind_speed_mps": 6.0, "airspeed_mps": 10.0, **variables},
    )


def test_heterogeneous_tools_share_one_registry() -> None:
    registry = load_registry()

    assert {manifest.fidelity for manifest in registry.manifests} == {
        FidelityClass.ANALYTICAL,
        FidelityClass.EMPIRICAL,
        FidelityClass.GEOMETRIC,
        FidelityClass.PHYSICS,
        FidelityClass.HIGH_FIDELITY_SIMULATION,
    }


def test_providers_compare_by_usability_fidelity_and_cost() -> None:
    options = load_registry().options("energy.route_demand", calm_multirotor())

    assert [option.manifest_key for option in options] == [
        "reference.momentum-energy@0.1.0",
        "isaac.closed-loop-flight@0.1.0",
    ]
    assert options[0].usable
    assert options[0].cost == CostClass.NEGLIGIBLE


def test_outside_validity_region_is_ranked_after_usable_options() -> None:
    options = load_registry().options(
        "energy.route_demand", calm_multirotor(wind_speed_mps=15.0)
    )

    assert options[0].manifest_key == "isaac.closed-loop-flight@0.1.0"
    assert options[1].validity.status == RegionStatus.OUTSIDE
    assert options[1].validity.violated == ("wind_speed_mps",)


def test_conditional_capability_is_not_offered_outside_conditions() -> None:
    registry = load_registry()
    vtol = OperatingContext(airframe="vtol", variables={"wind_speed_mps": 4.0})

    by_key = {
        option.manifest_key: option
        for option in registry.options("energy.route_demand", vtol)
    }

    assert not by_key["reference.momentum-energy@0.1.0"].usable
    assert by_key["reference.momentum-energy@0.1.0"].offered.violated == ("airframe",)
    reserve = registry.options("energy.reserve_assessment", vtol)
    assert reserve[0].usable


def test_missing_context_variable_is_unknown_not_valid() -> None:
    option = load_registry().options(
        "energy.route_demand", OperatingContext(airframe="multirotor")
    )[0]

    assert option.validity.status == RegionStatus.UNKNOWN
    assert set(option.validity.unknown) == {"wind_speed_mps", "airspeed_mps"}


def test_empirical_trust_region_is_reported_separately_from_validity() -> None:
    registry = load_registry()
    inside = registry.options(
        "dynamics.performance_margin",
        calm_multirotor(takeoff_mass_kg=4.0, temperature_c=20.0),
    )[0]
    extrapolated = registry.options(
        "dynamics.performance_margin",
        calm_multirotor(wind_speed_mps=12.0, takeoff_mass_kg=4.0, temperature_c=20.0),
    )[0]

    assert inside.trusted and inside.usable
    assert extrapolated.usable and not extrapolated.trusted


def test_provider_inherits_canonical_ports_and_restricted_measures() -> None:
    manifest = load_registry().get("fleet.wind-margin-regression@2.1.0")
    provision = manifest.provision("dynamics.performance_margin")

    assert provision.measures == ("control_margin", "control_saturation")
    assert {port.name for port in provision.inputs} == {
        "vehicle_envelope",
        "atmosphere",
        "wind_field",
    }


def test_opaque_provider_requires_validation_evidence() -> None:
    data = manifest_data("customer_battery_model.json")
    data["trust_regions"] = []

    with pytest.raises(ValidationError, match="opaque providers must declare"):
        ToolManifest.model_validate(data)

    data = manifest_data("customer_battery_model.json")
    data["execution_mode"] = "in_process"
    with pytest.raises(ValidationError, match="service boundary"):
        ToolManifest.model_validate(data)


def test_stochastic_provider_must_be_seedable() -> None:
    data = manifest_data("isaac_closed_loop.json")
    data["reproducibility"]["seed_controlled"] = False

    with pytest.raises(ValidationError, match="controlled seed"):
        ToolManifest.model_validate(data)


def test_registration_rejects_non_canonical_contracts() -> None:
    registry = ToolRegistry()
    data = manifest_data("analytic_energy.json")
    data["provides"][0]["inputs"].append({"name": "site_geometry", "kind": "site_geometry"})
    with pytest.raises(RegistrationError, match="non-canonical inputs"):
        registry.register(ToolManifest.model_validate(data))

    data = manifest_data("analytic_energy.json")
    data["provides"][1]["capability_id"] = "energy.teleport"
    with pytest.raises(RegistrationError, match="unknown capability"):
        registry.register(ToolManifest.model_validate(data))

    data = manifest_data("analytic_energy.json")
    data["errors"][0]["measure"] = "minimum_clearance_m"
    with pytest.raises(RegistrationError, match="unprovided measure"):
        registry.register(ToolManifest.model_validate(data))


def test_duplicate_versions_are_rejected() -> None:
    registry = load_registry()

    with pytest.raises(RegistrationError, match="already registered"):
        registry.register(ToolManifest.model_validate(manifest_data("analytic_energy.json")))
