import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from drone_sim.ir import DeploymentIR
from drone_sim.provenance import (
    Assumption,
    ConfidenceLevel,
    EvidenceBackedDeployment,
    EvidenceCandidate,
    ExtractionMethod,
    MaterialFact,
    SourceAnchor,
    SourceLocationType,
    Uncertainty,
    ValueOrigin,
    material_values,
)


FIXTURE = Path(__file__).parents[1] / "examples" / "demo_deployment.json"


def source_candidate(identifier: str, value: object) -> EvidenceCandidate:
    return EvidenceCandidate(
        id=identifier,
        value=value,
        origin=ValueOrigin.OBSERVED,
        sources=(
            SourceAnchor(
                source_path="deployment.json",
                location_type=SourceLocationType.JSON_POINTER,
                locator="/fixture",
                sha256="a" * 64,
            ),
        ),
        extraction=ExtractionMethod(name="json", version="1"),
        uncertainty=Uncertainty(
            confidence=ConfidenceLevel.MEDIUM,
            basis="The source does not state a calibrated confidence",
        ),
    )


def complete_evidence() -> dict:
    deployment = DeploymentIR.model_validate(json.loads(FIXTURE.read_text()))
    facts = tuple(
        MaterialFact(path=path, selected=source_candidate(f"fact-{index}", value))
        for index, (path, value) in enumerate(material_values(deployment).items())
    )
    return {"deployment": deployment, "facts": facts}


def test_complete_evidence_round_trips() -> None:
    evidence = EvidenceBackedDeployment(**complete_evidence())

    assert evidence.fact("/vehicle/mass_kg").selected.value == 4.2
    assert (
        EvidenceBackedDeployment.model_validate_json(evidence.model_dump_json())
        == evidence
    )


def test_every_material_field_requires_evidence() -> None:
    data = complete_evidence()
    data["facts"] = data["facts"][:-1]

    with pytest.raises(ValidationError, match="missing evidence for"):
        EvidenceBackedDeployment(**data)


def test_selected_value_must_match_deployment() -> None:
    data = complete_evidence()
    facts = list(data["facts"])
    index = next(i for i, fact in enumerate(facts) if fact.path == "/vehicle/mass_kg")
    facts[index] = MaterialFact(
        path="/vehicle/mass_kg", selected=source_candidate("wrong-mass", 5.0)
    )
    data["facts"] = tuple(facts)

    with pytest.raises(ValidationError, match="does not match /vehicle/mass_kg"):
        EvidenceBackedDeployment(**data)


def test_source_backed_values_require_an_exact_anchor() -> None:
    with pytest.raises(ValidationError, match="require a source anchor"):
        EvidenceCandidate(
            id="unanchored",
            value=4.2,
            origin=ValueOrigin.MANUFACTURER_SPECIFIED,
            extraction=ExtractionMethod(name="manual", version="1"),
            uncertainty=Uncertainty(
                confidence=ConfidenceLevel.HIGH, basis="Manufacturer data sheet"
            ),
        )


def test_assumptions_are_explicit_and_referentially_valid() -> None:
    assumed = EvidenceCandidate(
        id="assumed-wind",
        value=4.2,
        origin=ValueOrigin.ASSUMED,
        assumption_ids=("planned-mass",),
        extraction=ExtractionMethod(name="operator_assumption", version="1"),
        uncertainty=Uncertainty(
            confidence=ConfidenceLevel.LOW,
            basis="No site forecast was available",
        ),
    )
    assert assumed.assumption_ids == ("planned-mass",)

    with pytest.raises(ValidationError, match="require an explicit assumption"):
        EvidenceCandidate(
            id="implicit-assumption",
            value=5.0,
            origin=ValueOrigin.ASSUMED,
            extraction=ExtractionMethod(name="operator_assumption", version="1"),
            uncertainty=Uncertainty(
                confidence=ConfidenceLevel.LOW, basis="Missing weather evidence"
            ),
        )

    assumption = Assumption(
        id="planned-mass",
        description="Vehicle mass remains at 4.2 kg",
        rationale="Planning placeholder pending a measured takeoff mass",
    )
    data = complete_evidence()
    facts = list(data["facts"])
    index = next(i for i, fact in enumerate(facts) if fact.path == "/vehicle/mass_kg")
    facts[index] = MaterialFact(path="/vehicle/mass_kg", selected=assumed)
    data["facts"] = tuple(facts)

    with pytest.raises(ValidationError, match="unknown assumptions"):
        EvidenceBackedDeployment(**data)

    data["assumptions"] = (assumption,)
    evidence = EvidenceBackedDeployment(**data)
    assert evidence.assumptions == (assumption,)


def test_model_derived_lineage_must_reference_known_acyclic_candidates() -> None:
    data = complete_evidence()
    facts = list(data["facts"])
    mass_index = next(
        i for i, fact in enumerate(facts) if fact.path == "/vehicle/mass_kg"
    )
    speed_index = next(
        i for i, fact in enumerate(facts) if fact.path == "/vehicle/max_speed_mps"
    )
    mass_id = facts[mass_index].selected.id
    facts[speed_index] = MaterialFact(
        path="/vehicle/max_speed_mps",
        selected=EvidenceCandidate(
            id="derived-speed",
            value=15.0,
            origin=ValueOrigin.MODEL_DERIVED,
            derived_from=(mass_id,),
            extraction=ExtractionMethod(name="performance_model", version="2.1"),
            uncertainty=Uncertainty(
                confidence=ConfidenceLevel.MEDIUM,
                basis="Model validated only within the nominal mass range",
            ),
        ),
    )
    data["facts"] = tuple(facts)

    evidence = EvidenceBackedDeployment(**data)
    assert evidence.fact("/vehicle/max_speed_mps").selected.derived_from == (mass_id,)

    facts[speed_index] = MaterialFact(
        path="/vehicle/max_speed_mps",
        selected=facts[speed_index].selected.model_copy(
            update={"derived_from": ("missing-input",)}
        ),
    )
    data["facts"] = tuple(facts)
    with pytest.raises(ValidationError, match="unknown inputs"):
        EvidenceBackedDeployment(**data)
