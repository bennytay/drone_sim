from datetime import UTC, datetime
from pathlib import Path

from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.knowledge import KnowledgeKind, KnowledgeSource, KnowledgeUse
from drone_sim.knowledge_retrieval import retrieve_for_hypothesis, retrieve_knowledge


NOW = datetime(2026, 9, 28, tzinfo=UTC)


def test_retrieval_populates_folder_platform_operator_external_and_model_sources() -> None:
    operator = KnowledgeSource(
        id="operator-site-rule",
        kind=KnowledgeKind.SITE_RULE,
        title="Warehouse roof exclusion rule",
        locator="operator://site-rules/roof",
        retrieved_at=NOW,
        source_hash="1" * 64,
        use=KnowledgeUse.HYPOTHESIS_PROMPT,
        summary="Maintain clearance from rooftop structures.",
    )
    external = KnowledgeSource(
        id="external-forecast",
        kind=KnowledgeKind.ENVIRONMENTAL_CONTEXT,
        title="Wind forecast",
        locator="external://forecast/fictional",
        retrieved_at=NOW,
        source_hash="2" * 64,
        use=KnowledgeUse.HYPOTHESIS_PROMPT,
        summary="Gust conditions may exceed the steady forecast.",
    )
    bundle = retrieve_knowledge(
        Path("examples/demo_deployment"),
        operator_sources=(operator,),
        external_sources=(external,),
        model_world_prompts=("Battery reserve can motivate a route-demand hypothesis.",),
        retrieved_at=NOW,
    )

    assert len(
        [source for source in bundle.sources if source.kind == "platform_knowledge"]
    ) == len(DEFAULT_FAILURE_TAXONOMY.leaves())
    assert {"operator-site-rule", "external-forecast", "model-world-1"} <= {
        source.id for source in bundle.sources
    }
    assert all(
        source.locator and source.retrieved_at == NOW and source.source_hash
        for source in bundle.sources
    )
    assert all(source.use == "hypothesis_prompt" for source in bundle.sources)


def test_only_prompt_eligible_relevant_knowledge_is_ranked() -> None:
    bundle = retrieve_knowledge(
        Path("examples/demo_deployment"), retrieved_at=NOW
    )
    results = retrieve_for_hypothesis(bundle, "wind route reserve")
    assert results
    assert all(source.use == KnowledgeUse.HYPOTHESIS_PROMPT for source in results)
