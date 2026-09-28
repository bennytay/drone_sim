"""Provenance, recency, and precedence rules for hypothesis-enrichment knowledge."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from drone_sim.ir import StrictModel


class KnowledgeKind(StrEnum):
    DEPLOYMENT_EVIDENCE = "deployment_evidence"
    MANUFACTURER = "manufacturer"
    ENGINEERING_REFERENCE = "engineering_reference"
    REGULATION = "regulation"
    SITE_RULE = "site_rule"
    ENVIRONMENTAL_CONTEXT = "environmental_context"
    PLATFORM_KNOWLEDGE = "platform_knowledge"
    MODEL_WORLD_KNOWLEDGE = "model_world_knowledge"


class KnowledgeUse(StrEnum):
    FACT = "fact"
    HYPOTHESIS_PROMPT = "hypothesis_prompt"


_FACT_KINDS = {
    KnowledgeKind.DEPLOYMENT_EVIDENCE,
    KnowledgeKind.MANUFACTURER,
    KnowledgeKind.REGULATION,
    KnowledgeKind.SITE_RULE,
    KnowledgeKind.ENVIRONMENTAL_CONTEXT,
}


class KnowledgeSource(StrictModel):
    id: str = Field(min_length=1)
    kind: KnowledgeKind
    title: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    retrieved_at: datetime
    published_at: datetime | None = None
    source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    use: KnowledgeUse
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def permitted_use(self) -> KnowledgeSource:
        if self.use == KnowledgeUse.FACT and self.kind not in _FACT_KINDS:
            raise ValueError(
                "this knowledge kind may prompt a hypothesis but cannot establish a fact"
            )
        return self


class KnowledgeClaim(StrictModel):
    field: str = Field(min_length=1)
    value: str | float | bool
    source_id: str = Field(min_length=1)


class KnowledgeBundle(StrictModel):
    sources: tuple[KnowledgeSource, ...]
    claims: tuple[KnowledgeClaim, ...] = ()

    @model_validator(mode="after")
    def source_references_are_valid(self) -> KnowledgeBundle:
        ids = {source.id for source in self.sources}
        if len(ids) != len(self.sources) or any(
            claim.source_id not in ids for claim in self.claims
        ):
            raise ValueError(
                "knowledge sources must be unique and claims must reference them"
            )
        return self

    def prompts(self) -> tuple[KnowledgeSource, ...]:
        return tuple(
            source
            for source in self.sources
            if source.use == KnowledgeUse.HYPOTHESIS_PROMPT
        )

    def facts_for(self, field: str) -> tuple[KnowledgeClaim, ...]:
        """Return only fact-eligible claims, favoring deployment-local evidence."""
        sources = {source.id: source for source in self.sources}
        matches = [
            claim
            for claim in self.claims
            if claim.field == field
            and sources[claim.source_id].use == KnowledgeUse.FACT
        ]
        return tuple(
            sorted(
                matches,
                key=lambda claim: (
                    sources[claim.source_id].kind != KnowledgeKind.DEPLOYMENT_EVIDENCE,
                    sources[claim.source_id].retrieved_at,
                ),
                reverse=False,
            )
        )
