"""Operator-confirmed conflict and clarification records for deployment evidence."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from drone_sim.provenance import ConflictResolution, ResolutionMethod
from drone_sim.context import CandidateFact
from drone_sim.provenance import ConfidenceLevel, ValueOrigin
import hashlib
class ResolutionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    selected_candidate_id: str = Field(min_length=1)
    rejected_candidate_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
def confirm_resolution(proposal: ResolutionProposal, *, operator_confirmed: bool) -> ConflictResolution:
    if not operator_confirmed: raise PermissionError("conflict resolution requires explicit operator confirmation")
    if not proposal.rejected_candidate_ids: raise ValueError("a conflict resolution must reject competing candidates")
    return ConflictResolution(method=ResolutionMethod.OPERATOR_DECISION, selected_candidate_id=proposal.selected_candidate_id, rejected_candidate_ids=proposal.rejected_candidate_ids, rationale=proposal.rationale)

def operator_answer_candidate(*, field: str, value: object, operator_id: str, rationale: str) -> CandidateFact:
    """Turn a scripted or interactive operator answer into auditable observed evidence."""
    source = f"operator:{operator_id}"
    return CandidateFact(field=field, value=value, source_path=source, adapter="operator_confirmation", source_location="answer", source_sha256=hashlib.sha256(source.encode()).hexdigest(), origin=ValueOrigin.OBSERVED, confidence=ConfidenceLevel.HIGH, uncertainty_basis=rationale)
