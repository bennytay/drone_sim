from datetime import UTC, datetime
from pathlib import Path

from drone_sim.context import ContextOrchestrator, DirectoryIndex, FileRecord
from drone_sim.llm import LLMResponse, StructuredOutputRunner
from drone_sim.semantic_ranking import (
    LLMSemanticRanker,
    MetadataSemanticRanker,
    evaluate_ranking,
)


def test_metadata_ranker_finds_synonym_without_reading_content() -> None:
    records = (
        FileRecord(
            path="exports/uav_specs.pdf",
            size_bytes=1,
            modified_at=datetime.now(UTC),
            modified_at_ns=1,
        ),
        FileRecord(
            path="notes.txt",
            size_bytes=1,
            modified_at=datetime.now(UTC),
            modified_at_ns=1,
        ),
    )
    assert (
        MetadataSemanticRanker().rank("aircraft limits", records)[0]
        == "exports/uav_specs.pdf"
    )


def test_directory_search_accepts_metadata_only_ranker() -> None:
    index = DirectoryIndex.build(Path("examples/demo_deployment"))
    results = index.search("aircraft", semantic_ranker=MetadataSemanticRanker())
    assert results[0].path.startswith("aircraft/")


def test_ranker_caches_by_index_signature_and_reduces_candidates() -> None:
    index = DirectoryIndex.build(Path("examples/demo_deployment"))
    ranker = MetadataSemanticRanker()
    cases = (
        ("aircraft limits", "aircraft/approved_current_aircraft.json"),
        ("battery specification", "operations/battery_spec.md"),
        ("route plan", "mission/flight_plan.json"),
    )
    metrics = evaluate_ranking(ranker, index.records, cases, limit=5)
    first = ranker.computations
    evaluate_ranking(ranker, index.records, cases, limit=5)
    assert metrics.recall_at_limit == 1
    assert metrics.mean_files_returned < len(index.records)
    assert ranker.computations == first


def test_ranked_reconstruction_preserves_fields_and_opens_fewer_files(tmp_path) -> None:
    root = Path("examples/demo_deployment")
    baseline, baseline_state = ContextOrchestrator(
        root, tmp_path / "baseline.json"
    ).run()
    ranked, ranked_state = ContextOrchestrator(
        root,
        tmp_path / "ranked.json",
        semantic_ranker=MetadataSemanticRanker(),
    ).run()

    assert baseline is not None and ranked is not None
    assert ranked.deployment == baseline.deployment
    assert len(ranked_state.inspected_paths) < len(baseline_state.inspected_paths)


def test_llm_ranker_sends_metadata_only_and_persists_cache(tmp_path) -> None:
    class Replay:
        calls = 0

        def complete(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            payload = request.prompt.messages[-1].content
            assert "secret file contents" not in payload
            assert '"size_bytes": 1' in payload
            return LLMResponse(
                model=request.model,
                prompt_id=request.prompt.id,
                prompt_version=request.prompt.version,
                text='{"paths":["exports/uav_specs.pdf"]}',
            )

    records = (
        FileRecord(
            path="exports/uav_specs.pdf",
            size_bytes=1,
            modified_at=datetime.now(UTC),
            modified_at_ns=1,
        ),
    )
    provider = Replay()
    cache = tmp_path / "rankings.json"
    ranker = LLMSemanticRanker(
        StructuredOutputRunner(provider), model="replay", cache_path=cache
    )
    assert ranker.rank("aircraft", records) == ("exports/uav_specs.pdf",)
    reloaded = LLMSemanticRanker(
        StructuredOutputRunner(provider), model="replay", cache_path=cache
    )
    assert reloaded.rank("aircraft", records) == ("exports/uav_specs.pdf",)
    assert provider.calls == 1
