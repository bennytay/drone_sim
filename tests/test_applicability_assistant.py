from drone_sim.applicability_assistant import ApplicabilityProposal
from drone_sim.coverage import ApplicabilityRule, EvidencePredicate
def test_proposal_only_targets_drone_taxonomy_leaf() -> None:
    proposal = ApplicabilityProposal(mechanism_id="environment_weather.wind.steady_limit", rule=ApplicabilityRule(all_of=(EvidencePredicate(path="/conditions/wind_speed_mps", description="wind available"),)), rationale="wind forecast exists")
    assert proposal.rule.all_of[0].path == "/conditions/wind_speed_mps"
