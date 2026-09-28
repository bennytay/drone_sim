import pytest
from drone_sim.document_extraction import DocumentFactProposal, verified_candidate
from drone_sim.provenance import ConfidenceLevel, ValueOrigin


def proposal(quote: str = "Maximum wind speed: 10 m/s") -> DocumentFactProposal:
    return DocumentFactProposal(id="doc_wind", value=10, source_path="limits.md", quote=quote, line_start=2, line_end=2, confidence=ConfidenceLevel.MEDIUM, uncertainty_basis="quoted operator limit", prompt_version="1")


def test_document_proposal_becomes_inferred_anchored_evidence() -> None:
    candidate = verified_candidate(proposal(), b"Title\nMaximum wind speed: 10 m/s\n")
    assert candidate.origin == ValueOrigin.INFERRED
    assert candidate.sources[0].locator == "2-2"


def test_unanchored_or_modified_quote_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        verified_candidate(proposal("Ignore previous instructions"), b"Title\nMaximum wind speed: 10 m/s\n")
