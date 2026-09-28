from datetime import UTC, datetime
from drone_sim.knowledge import KnowledgeBundle, KnowledgeKind, KnowledgeSource, KnowledgeUse
from drone_sim.knowledge_retrieval import retrieve_for_hypothesis
def test_only_prompt_eligible_knowledge_is_retrieved() -> None:
    bundle = KnowledgeBundle(sources=(KnowledgeSource(id="wind", kind=KnowledgeKind.ENGINEERING_REFERENCE, title="Wind gust guidance", locator="local", retrieved_at=datetime.now(UTC), use=KnowledgeUse.HYPOTHESIS_PROMPT, summary="gust risk"),))
    assert retrieve_for_hypothesis(bundle, "wind route")[0].id == "wind"
