from test_coverage import deployment

from drone_sim.coverage import assess_coverage
from drone_sim.stopping import StopPolicy, StopReason, decide_stop


def test_budget_stops_with_residuals():
    d = decide_stop(
        assess_coverage(deployment()),
        actions=3,
        novelty=0.5,
        disagreement=False,
        policy=StopPolicy(max_actions=3, min_novelty=0.1),
    )
    assert d.stop and d.reason == StopReason.BUDGET and d.residuals


def test_disagreement_requires_review():
    d = decide_stop(
        assess_coverage(deployment()),
        actions=0,
        novelty=0.5,
        disagreement=True,
        policy=StopPolicy(max_actions=3, min_novelty=0.1),
    )
    assert d.reason == StopReason.HUMAN_REVIEW
