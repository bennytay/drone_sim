"""Deterministic selection of provenance-qualified knowledge for hypotheses."""
from drone_sim.knowledge import KnowledgeBundle, KnowledgeSource
def retrieve_for_hypothesis(bundle: KnowledgeBundle, query: str) -> tuple[KnowledgeSource, ...]:
    tokens = set(query.lower().split())
    return tuple(source for source in bundle.prompts() if tokens & set((source.title + " " + source.summary).lower().split()))
