from test_investigation import state

from drone_sim.investigation_loop import InvestigationTrace, advance


def test_loop_records_selected_action() -> None:
    _state, trace = advance(state(), InvestigationTrace())
    assert trace.actions[0].hypothesis_id == "hyp_wind_margin"
