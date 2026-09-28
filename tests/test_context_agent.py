import json
from pathlib import Path

from drone_sim.context import ContextOrchestrator, DeploymentState
from drone_sim.context_agent import (
    ContextActionKind,
    ContextAgentLoop,
    ContextPolicy,
    LLMDocumentExtractor,
    LLMSchemaExtractor,
    record_action,
)
from drone_sim.llm import LLMResponse, StructuredOutputRunner


class Replay:
    def __init__(self, payloads: list[dict[str, object]]):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        payload = self.payloads.pop(0)
        return LLMResponse(
            model=request.model,
            prompt_id=request.prompt.id,
            prompt_version=request.prompt.version,
            text=json.dumps(payload),
        )


def search(field: str, query: str, *, limit: int = 1) -> dict[str, object]:
    return {
        "kind": "search",
        "field": field,
        "query": query,
        "limit": limit,
        "rationale": f"Inspect metadata matching {query} for unresolved {field}",
    }


STOP = {
    "kind": "stop",
    "field": None,
    "query": None,
    "limit": 3,
    "rationale": "No remaining metadata is likely to resolve the finding",
}


def test_context_policy_stops_explicitly_or_selects_unresolved_field() -> None:
    policy = ContextPolicy()
    assert (
        policy.choose(
            ("/vehicle/mass_kg",), calls_used=0, max_calls=2
        ).field
        == "vehicle"
    )
    assert (
        policy.choose(
            ("/vehicle/mass_kg",), calls_used=2, max_calls=2
        ).rationale
        == "budget_exhausted"
    )
    assert (
        policy.choose((), calls_used=0, max_calls=2).kind
        == ContextActionKind.STOP
    )


def test_agent_action_is_persisted_in_context_trace() -> None:
    state = DeploymentState(root="/tmp/fake")
    action = ContextPolicy().choose(
        ("/vehicle/mass_kg",), calls_used=0, max_calls=2
    )
    record_action(state, action)
    assert state.trace[-1].field == "vehicle"
    assert "Highest-priority" in state.trace[-1].reason


def test_replay_agent_matches_synthetic_readiness_with_fewer_files(tmp_path) -> None:
    corpus = Path("examples/synthetic_deployments")
    cases = {
        "01_rooftop-inspection_clean": (
            "ready",
            [search("deployment_id", "approved current deployment")],
        ),
        "02_solar-farm-survey_messy": (
            "ready",
            [search("deployment_id", "final export")],
        ),
        "03_coastal-turbine_conflicting": (
            "conflicting",
            [search("deployment_id", "manifest", limit=2), STOP],
        ),
        "04_quarry-mapping_incomplete": (
            "incomplete",
            [search("deployment_id", "partial notes"), STOP],
        ),
        "05_bridge-inspection_split": (
            "ready",
            [
                search("deployment_id", "box a"),
                search("vehicle", "box b"),
                search("mission", "box c"),
                search("site", "box d"),
                search("autonomy", "box e"),
                search("success_criteria", "box f"),
            ],
        ),
        "06_night-search_invalid_unit": (
            "invalid",
            [search("deployment_id", "approved current deployment"), STOP],
        ),
    }
    baseline_files = agent_files = 0
    for folder, (expected, actions) in cases.items():
        root = corpus / folder
        baseline = ContextOrchestrator(root, tmp_path / f"{folder}.baseline.json")
        _, baseline_state = baseline.run()
        baseline_files += len(baseline_state.inspected_paths)

        replay = Replay(actions)
        result = ContextAgentLoop(
            root,
            tmp_path / f"{folder}.agent.json",
            runner=StructuredOutputRunner(replay),
            model="replay",
            tool_ledger_path=tmp_path / f"{folder}.tools.json",
        ).run()
        agent_files += len(result.state.inspected_paths)
        assert result.readiness.status == expected
        assert result.state.trace[-1].query == "stop"
        assert all(event.reason for event in result.state.trace)

    assert (agent_files, baseline_files) == (12, 29)


def test_document_heavy_replay_extracts_verified_fact_and_resumes(tmp_path) -> None:
    source = json.loads(
        Path(
            "examples/synthetic_deployments/01_rooftop-inspection_clean/"
            "approved_current_deployment.json"
        ).read_text()
    )
    source.pop("success_criteria")
    root = tmp_path / "document-heavy"
    (root / "records").mkdir(parents=True)
    (root / "documents").mkdir()
    (root / "records" / "packet.json").write_text(json.dumps(source))
    (root / "documents" / "acceptance_rules.txt").write_text(
        "Route completion must be at least 98%.\n"
    )
    for index in range(8):
        (root / "documents" / f"archive-{index}.txt").write_text(
            "Historical operator note; not an approved deployment fact.\n"
        )

    baseline = ContextOrchestrator(root, tmp_path / "document-baseline.json")
    _, baseline_state = baseline.run()
    decision_replay = Replay(
        [
            search("deployment_id", "packet"),
            search("success_criteria", "acceptance rules"),
            STOP,
        ]
    )
    document_replay = Replay(
        [
            {
                "proposals": [
                    {
                        "id": "route-completion-doc",
                        "value": [
                            {
                                "id": "route-completion",
                                "metric": "route_completion_ratio",
                                "operator": "gte",
                                "target": 0.98,
                                "unit": "ratio",
                            }
                        ],
                        "source_path": "documents/acceptance_rules.txt",
                        "quote": "Route completion must be at least 98%.",
                        "line_start": 1,
                        "line_end": 1,
                        "page_number": None,
                        "confidence": "medium",
                        "uncertainty_basis": "Exact operator-authored acceptance statement",
                        "prompt_version": "1",
                        "conversion": "identity",
                    }
                ]
            }
        ]
    )
    state_path = tmp_path / "document-agent.json"
    loop = ContextAgentLoop(
        root,
        state_path,
        runner=StructuredOutputRunner(decision_replay),
        model="replay",
        supplemental_extractor=LLMDocumentExtractor(
            root, StructuredOutputRunner(document_replay), model="replay"
        ),
    )
    result = loop.run()

    assert result.readiness.status == "uncertain"
    assert result.evidence is not None
    assert len(result.state.inspected_paths) < len(baseline_state.inspected_paths)
    assert result.state.candidates["success_criteria"][0].origin == "inferred"
    resumed = ContextAgentLoop(
        root,
        state_path,
        runner=StructuredOutputRunner(Replay([])),
        model="replay",
    ).run()
    assert resumed.stop_reason == "model_stop"
    assert resumed.evidence == result.evidence


def test_agent_applies_replayed_schema_mapping_to_unfamiliar_json(tmp_path) -> None:
    root = tmp_path / "mapped"
    root.mkdir()
    (root / "vendor_blob.json").write_text(
        json.dumps({"operation": {"reference": "mapped-drone-deployment"}})
    )
    decisions = Replay([search("deployment_id", "vendor blob"), STOP])
    mappings = Replay(
        [
            {
                "mappings": [
                    {
                        "source_pointer": "/operation/reference",
                        "canonical_path": "/deployment_id",
                        "conversion": "identity",
                    }
                ]
            }
        ]
    )
    result = ContextAgentLoop(
        root,
        tmp_path / "mapped-state.json",
        runner=StructuredOutputRunner(decisions),
        model="replay",
        supplemental_extractor=LLMSchemaExtractor(
            StructuredOutputRunner(mappings), model="replay"
        ),
    ).run()

    candidate = result.state.candidates["deployment_id"][0]
    assert candidate.value == "mapped-drone-deployment"
    assert candidate.source_location == "/operation/reference"


def test_agent_records_budget_stop(tmp_path) -> None:
    root = tmp_path / "budget"
    root.mkdir()
    (root / "note.txt").write_text("No canonical deployment data.\n")
    result = ContextAgentLoop(
        root,
        tmp_path / "budget-state.json",
        runner=StructuredOutputRunner(
            Replay([search("deployment_id", "note")])
        ),
        model="replay",
        max_decisions=1,
    ).run()

    assert result.stop_reason == "budget_exhausted"
    assert result.state.trace[-1].reason == "budget_exhausted"


def test_index_change_reopens_a_no_evidence_stop(tmp_path) -> None:
    root = tmp_path / "changing"
    root.mkdir()
    (root / "note.txt").write_text("Nothing relevant.\n")
    state_path = tmp_path / "changing-state.json"
    first = ContextAgentLoop(
        root,
        state_path,
        runner=StructuredOutputRunner(
            Replay([search("deployment_id", "missing evidence")])
        ),
        model="replay",
    ).run()
    assert first.stop_reason == "no_promising_evidence"

    (root / "target.json").write_text(
        json.dumps({"deployment_id": "new-drone-deployment"})
    )
    replay = Replay([search("deployment_id", "target"), STOP])
    resumed = ContextAgentLoop(
        root,
        state_path,
        runner=StructuredOutputRunner(replay),
        model="replay",
    ).run()

    assert resumed.state.candidates["deployment_id"][0].value == "new-drone-deployment"
    assert replay.calls == 2
