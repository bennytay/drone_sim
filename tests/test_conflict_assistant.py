import pytest
from drone_sim.conflict_assistant import ResolutionProposal, confirm_resolution, operator_answer_candidate
from drone_sim.provenance import ValueOrigin
from drone_sim.provenance import ResolutionMethod

def test_only_operator_confirmation_creates_resolution() -> None:
    proposal = ResolutionProposal(selected_candidate_id="current", rejected_candidate_ids=("stale",), rationale="operator reviewed source dates")
    with pytest.raises(PermissionError): confirm_resolution(proposal, operator_confirmed=False)
    assert confirm_resolution(proposal, operator_confirmed=True).method == ResolutionMethod.OPERATOR_DECISION

def test_scripted_operator_answer_has_observed_provenance() -> None:
    answer = operator_answer_candidate(field="vehicle", value={"id": "uav"}, operator_id="operator-1", rationale="operator supplied approved record")
    assert answer.origin == ValueOrigin.OBSERVED
    assert answer.source_path == "operator:operator-1"
