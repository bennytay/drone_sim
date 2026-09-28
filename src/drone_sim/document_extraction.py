"""Validated conversion of bounded document-extraction proposals to evidence."""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.provenance import (
    ConfidenceLevel, EvidenceCandidate, ExtractionMethod, SourceAnchor,
    SourceLocationType, Uncertainty, ValueOrigin,
)


class DocumentFactProposal(BaseModel):
    """Only a proposal; deterministic code checks its exact quoted evidence."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    value: object
    source_path: str
    quote: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    confidence: ConfidenceLevel
    uncertainty_basis: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


def verified_candidate(proposal: DocumentFactProposal, source_bytes: bytes) -> EvidenceCandidate:
    """Reject quotes/line spans that do not exactly match the inspected document."""
    text = source_bytes.decode("utf-8")
    lines = text.splitlines()
    if proposal.line_end < proposal.line_start or proposal.line_end > len(lines):
        raise ValueError("proposal line span is outside source text")
    span = "\n".join(lines[proposal.line_start - 1:proposal.line_end])
    if proposal.quote != span:
        raise ValueError("proposal quote does not exactly match the source line span")
    digest = hashlib.sha256(source_bytes).hexdigest()
    return EvidenceCandidate(
        id=proposal.id, value=proposal.value, origin=ValueOrigin.INFERRED,
        sources=(SourceAnchor(source_path=proposal.source_path, location_type=SourceLocationType.TEXT_LINES, locator=f"{proposal.line_start}-{proposal.line_end}", sha256=digest),),
        extraction=ExtractionMethod(name="llm_document_extraction", version=proposal.prompt_version),
        uncertainty=Uncertainty(confidence=proposal.confidence, basis=proposal.uncertainty_basis),
    )
