from drone_sim.provenance import (
    ConfidenceLevel,
    ConflictResolution,
    EvidenceBackedDeployment,
    ResolutionMethod,
    material_values,
)
from drone_sim.ir import DeploymentIR
from drone_sim.validation import (
    Dependency,
    EvaluationProfile,
    ReadinessStatus,
    assess_evidence,
)

from test_provenance import complete_evidence, source_candidate


def test_complete_high_confidence_evidence_is_ready() -> None:
    data = complete_evidence()
    evidence = EvidenceBackedDeployment(**data)

    report = assess_evidence(evidence)

    assert report.status == ReadinessStatus.READY
    assert report.ready
    assert report.findings == ()


def test_profile_reports_missing_and_uncertain_dependencies() -> None:
    data = complete_evidence()
    evidence = EvidenceBackedDeployment(**data)
    profile = EvaluationProfile(
        id="wind_envelope_v1",
        description="Inputs required for steady-wind envelope analysis",
        dependencies=(
            Dependency(
                path="/conditions/wind_speed_mps",
                description="Site wind speed",
                minimum_confidence=ConfidenceLevel.HIGH,
            ),
            Dependency(path="/vehicle/nonexistent", description="Missing limit"),
        ),
    )

    report = assess_evidence(evidence, profile)

    assert report.status == ReadinessStatus.INCOMPLETE
    assert {finding.code for finding in report.findings} == {
        "missing_dependency",
        "uncertain_value",
    }


def test_explicit_resolution_clears_a_conflict() -> None:
    data = complete_evidence()
    facts = list(data["facts"])
    index = next(i for i, fact in enumerate(facts) if fact.path == "/vehicle/mass_kg")
    original = facts[index]
    competitor = original.selected.model_copy(
        update={"id": "alternate-mass", "value": 4.5}
    )
    facts[index] = original.model_copy(update={"competing": (competitor,)})
    data["facts"] = tuple(facts)
    unresolved = EvidenceBackedDeployment(**data)
    assert assess_evidence(unresolved).status == ReadinessStatus.CONFLICTING

    resolution = ConflictResolution(
        method=ResolutionMethod.SOURCE_PRIORITY,
        selected_candidate_id=original.selected.id,
        rejected_candidate_ids=(competitor.id,),
        rationale="The selected source is the signed aircraft release record",
    )
    facts[index] = facts[index].model_copy(update={"resolution": resolution})
    data["facts"] = tuple(facts)
    resolved = EvidenceBackedDeployment(**data)

    assert assess_evidence(resolved).status == ReadinessStatus.READY


def test_noncanonical_units_are_invalid() -> None:
    data = complete_evidence()
    deployment_data = data["deployment"].model_dump(mode="json")
    deployment_data["constraints"][0]["unit"] = "mph"
    deployment = DeploymentIR.model_validate(deployment_data)
    facts = tuple(
        {
            "path": path,
            "selected": source_candidate(f"unit-fact-{index}", value),
        }
        for index, (path, value) in enumerate(material_values(deployment).items())
    )
    evidence = EvidenceBackedDeployment(deployment=deployment, facts=facts)

    report = assess_evidence(evidence)

    assert report.status == ReadinessStatus.INVALID
    assert "/constraints/0/unit" in report.unresolved_paths
