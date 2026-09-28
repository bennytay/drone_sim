import pytest
from drone_sim.document_extraction import DocumentFactProposal, extract_document_candidates, verified_candidate, verified_context_candidate
from drone_sim.llm import LLMMessage, LLMResponse, LLMTask, MessageRole, Prompt, StructuredOutputRunner
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


def test_verified_proposal_becomes_conflict_preserving_context_candidate() -> None:
    candidate = verified_context_candidate(field="vehicle", proposal=proposal(), source_bytes=b"Title\nMaximum wind speed: 10 m/s\n")
    assert candidate.origin == ValueOrigin.INFERRED
    assert candidate.source_location == "2-2"


def test_replay_runner_only_admits_verified_document_proposals() -> None:
    class Replay:
        def complete(self, request):  # type: ignore[no-untyped-def]
            return LLMResponse(model=request.model, prompt_id=request.prompt.id, prompt_version=request.prompt.version, text='{"proposals":[{"id":"doc_wind","value":10,"source_path":"limits.md","quote":"Maximum wind speed: 10 m/s","line_start":2,"line_end":2,"confidence":"medium","uncertainty_basis":"quoted","prompt_version":"1"}]}')
    candidates = extract_document_candidates(runner=StructuredOutputRunner(Replay()), model="replay", prompt=Prompt(id="doc", version="1", messages=(LLMMessage(role=MessageRole.USER, content="extract"),)), field="vehicle", source_bytes=b"Title\nMaximum wind speed: 10 m/s\n")
    assert candidates[0].value == 10
