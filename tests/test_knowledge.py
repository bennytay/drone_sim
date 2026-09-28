from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from drone_sim.knowledge import (
    KnowledgeBundle,
    KnowledgeClaim,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeUse,
)


def source(identifier: str, kind: KnowledgeKind, use: KnowledgeUse) -> KnowledgeSource:
    return KnowledgeSource(
        id=identifier,
        kind=kind,
        use=use,
        title=identifier,
        locator="https://example.test",
        retrieved_at=datetime(2026, 9, 28, tzinfo=UTC),
        summary="Bounded source summary",
    )


def test_generic_knowledge_is_prompt_only() -> None:
    with pytest.raises(ValidationError, match="cannot establish a fact"):
        source("world", KnowledgeKind.MODEL_WORLD_KNOWLEDGE, KnowledgeUse.FACT)


def test_deployment_evidence_precedes_external_facts() -> None:
    bundle = KnowledgeBundle(
        sources=(
            source("external", KnowledgeKind.ENVIRONMENTAL_CONTEXT, KnowledgeUse.FACT),
            source("customer", KnowledgeKind.DEPLOYMENT_EVIDENCE, KnowledgeUse.FACT),
        ),
        claims=(
            KnowledgeClaim(field="wind_limit", value=10.0, source_id="external"),
            KnowledgeClaim(field="wind_limit", value=8.0, source_id="customer"),
        ),
    )
    assert bundle.facts_for("wind_limit")[0].source_id == "customer"


def test_claims_must_name_a_known_source() -> None:
    with pytest.raises(ValidationError, match="reference them"):
        KnowledgeBundle(
            sources=(
                source(
                    "customer", KnowledgeKind.DEPLOYMENT_EVIDENCE, KnowledgeUse.FACT
                ),
            ),
            claims=(KnowledgeClaim(field="site", value="x", source_id="missing"),),
        )
