import pytest
from pydantic import ValidationError

from drone_sim.capabilities import (
    DEFAULT_CAPABILITY_ONTOLOGY,
    DEFAULT_MECHANISM_CAPABILITIES,
    VENDOR_TERMS,
    Capability,
    CapabilityDomain,
    CapabilityKind,
    CapabilityOntology,
    DataKind,
    MechanismBinding,
    MechanismCapabilityMap,
)
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY


def test_ontology_covers_every_capability_domain() -> None:
    domains = {capability.domain for capability in DEFAULT_CAPABILITY_ONTOLOGY.capabilities}

    assert domains == set(CapabilityDomain)


def test_every_taxonomy_mechanism_is_expressible_as_capabilities() -> None:
    problems = DEFAULT_MECHANISM_CAPABILITIES.validate_against(
        DEFAULT_CAPABILITY_ONTOLOGY, DEFAULT_FAILURE_TAXONOMY
    )

    assert problems == ()


def test_bindings_do_not_name_vendor_tools() -> None:
    text = DEFAULT_MECHANISM_CAPABILITIES.model_dump_json().lower()
    text += DEFAULT_CAPABILITY_ONTOLOGY.model_dump_json().lower()

    assert not [term for term in VENDOR_TERMS if term in text]


def test_representative_hypothesis_resolves_to_capabilities() -> None:
    binding = DEFAULT_MECHANISM_CAPABILITIES.binding(
        "energy_battery.reserve.route_demand"
    )

    assert "energy.route_demand" in binding.required
    assert "energy.reserve_assessment" in binding.required
    assert DEFAULT_CAPABILITY_ONTOLOGY.get("energy.route_demand").output_kinds == {
        DataKind.BATTERY_STATE
    }


def test_closed_loop_composites_name_atomic_components() -> None:
    flight = DEFAULT_CAPABILITY_ONTOLOGY.get("autonomy.closed_loop_flight")

    assert flight.kind == CapabilityKind.COMPOSITE
    assert flight.closed_loop
    assert all(
        DEFAULT_CAPABILITY_ONTOLOGY.get(component).kind == CapabilityKind.ATOMIC
        for component in flight.composed_of
    )


def test_every_intermediate_kind_has_a_producer() -> None:
    consumed = {
        kind
        for capability in DEFAULT_CAPABILITY_ONTOLOGY.capabilities
        for kind in capability.input_kinds
    } - {DataKind.DEPLOYMENT}

    for kind in consumed:
        assert DEFAULT_CAPABILITY_ONTOLOGY.producers(kind), kind


def test_vendor_named_capability_is_rejected() -> None:
    data = DEFAULT_CAPABILITY_ONTOLOGY.model_dump()
    data["capabilities"][0]["description"] = "Run the Isaac Sim wind plugin"

    with pytest.raises(ValidationError, match="names vendor tools: isaac"):
        CapabilityOntology.model_validate(data)


def test_capability_id_must_match_domain() -> None:
    with pytest.raises(ValidationError, match="prefixed by its domain"):
        Capability(
            id="energy.wind_field",
            domain=CapabilityDomain.WEATHER,
            name="Misplaced",
            description="Wrong domain prefix",
            inputs=({"name": "deployment", "kind": DataKind.DEPLOYMENT},),
            outputs=({"name": "wind_field", "kind": DataKind.WIND_FIELD},),
        )


def test_incomplete_binding_reports_unproduced_inputs_and_outcomes() -> None:
    mapping = MechanismCapabilityMap(
        ontology_version=DEFAULT_CAPABILITY_ONTOLOGY.version,
        taxonomy_version=DEFAULT_FAILURE_TAXONOMY.version,
        bindings=(
            MechanismBinding(
                mechanism_id="energy_battery.reserve.route_demand",
                required=("energy.reserve_assessment",),
                rationale="Missing the demand model",
            ),
        ),
    )

    problems = mapping.validate_against(
        DEFAULT_CAPABILITY_ONTOLOGY, DEFAULT_FAILURE_TAXONOMY
    )

    assert any("battery_state are not produced" in problem for problem in problems)
    assert any("remaining_energy_wh" in problem for problem in problems)
    assert any("no capability binding" in problem for problem in problems)
