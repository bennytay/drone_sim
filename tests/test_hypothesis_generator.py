import copy
import json
from pathlib import Path

import pytest

from drone_sim.context import ContextOrchestrator
from drone_sim.coverage import assess_coverage
from drone_sim.hypothesis_generator import generate_hypotheses
from drone_sim.llm import LLMResponse, StructuredOutputRunner
from drone_sim.knowledge_retrieval import retrieve_knowledge


class Replay:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def complete(self, request):  # type: ignore[no-untyped-def]
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=json.dumps(self.payload),
        )


def demo_evidence(tmp_path: Path):  # type: ignore[no-untyped-def]
    orchestrator = ContextOrchestrator(
        Path("examples/demo_deployment"), tmp_path / "state.json"
    )
    evidence, _ = orchestrator.run()
    assert evidence is not None
    return evidence


def replay_hypotheses() -> dict[str, object]:
    return json.loads(Path("examples/replays/demo_agent_replay.json").read_text())[
        "hypotheses"
    ]


def test_demo_generation_is_grounded_measurable_and_coverage_accounted(
    tmp_path: Path,
) -> None:
    evidence = demo_evidence(tmp_path)
    knowledge = retrieve_knowledge(Path("examples/demo_deployment"))
    result = generate_hypotheses(
        runner=StructuredOutputRunner(Replay(replay_hypotheses())),
        model="replay",
        evidence=evidence,
        coverage=assess_coverage(evidence.deployment),
        knowledge=knowledge,
    )

    assert {item.id for item in result.contract.hypotheses} >= {
        "hyp_energy_reserve",
        "hyp_takeoff_mass",
        "hyp_roof_clearance",
    }
    assert result.issues == ()
    covered = {
        entry.mechanism_id
        for entry in result.coverage
        if entry.state == "covered"
    }
    assert covered >= {
        "energy_battery.reserve.route_demand",
        "vehicle_operating_envelope.loading.mass",
        "geometry_clearance.route.static_obstacle",
    }
    assert any(entry.state == "missing" for entry in result.coverage)
    assert all(
        any(reference.kind == "internal_knowledge" for reference in item.supporting_references)
        for item in result.contract.hypotheses
    )


def test_unknown_evidence_reference_fails_closed(tmp_path: Path) -> None:
    evidence = demo_evidence(tmp_path)
    payload = replay_hypotheses()
    payload["hypotheses"][0]["supporting_references"][0]["reference_id"] = (
        "/not/a/real/fact"
    )
    with pytest.raises(ValueError, match="unknown evidence reference"):
        generate_hypotheses(
            runner=StructuredOutputRunner(Replay(payload)),
            model="replay",
            evidence=evidence,
            coverage=assess_coverage(evidence.deployment),
        )


def test_unmeasurable_observable_is_flagged_not_dropped(tmp_path: Path) -> None:
    evidence = demo_evidence(tmp_path)
    payload = replay_hypotheses()
    payload["hypotheses"][0]["confirm_if"][0]["observable"] = "imaginary_metric"
    result = generate_hypotheses(
        runner=StructuredOutputRunner(Replay(payload)),
        model="replay",
        evidence=evidence,
        coverage=assess_coverage(evidence.deployment),
    )

    assert result.contract.hypotheses[0].id == "hyp_energy_reserve"
    assert result.issues[0].unmeasurable_observables == ("imaginary_metric",)
    assert next(
        entry
        for entry in result.coverage
        if entry.mechanism_id == "energy_battery.reserve.route_demand"
    ).state == "unmeasurable"


def test_duplicate_proposals_are_merged_before_strict_contract(tmp_path: Path) -> None:
    evidence = demo_evidence(tmp_path)
    payload = replay_hypotheses()
    duplicate = copy.deepcopy(payload["hypotheses"][0])
    duplicate["id"] = "hyp_energy_reserve_duplicate"
    payload["hypotheses"].append(duplicate)
    result = generate_hypotheses(
        runner=StructuredOutputRunner(Replay(payload)),
        model="replay",
        evidence=evidence,
        coverage=assess_coverage(evidence.deployment),
    )

    merged = next(
        item
        for item in result.contract.hypotheses
        if item.id == "hyp_energy_reserve_duplicate"
    )
    assert merged.status == "merged"
    assert merged.merged_into == "hyp_energy_reserve"
