from test_coverage import deployment
from test_hypothesis import hypothesis

from drone_sim.coverage import assess_coverage
from drone_sim.investigation import (
    ActionKind,
    InvestigationState,
    ResultKind,
    TestResult,
    apply_result,
    next_action,
)


def state():
    return InvestigationState(
        hypotheses=(hypothesis(),), coverage=assess_coverage(deployment())
    )


def test_selects_unresolved_material_hypothesis():
    assert next_action(state()).kind == ActionKind.TEST


def test_inconclusive_escalates_fidelity():
    s = apply_result(
        state(),
        TestResult(
            hypothesis_id="hyp_wind_margin",
            kind=ResultKind.INCONCLUSIVE,
            summary="insufficient",
            fidelity=0,
        ),
    )
    assert next_action(s).kind == ActionKind.ESCALATE
    assert next_action(s).fidelity == 1
