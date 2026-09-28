"""Golden Path: the closest current approximation of the product workflow.

Expected values here are the ones documented in docs/DEMO.md. If a change
alters them, update the demo documentation in the same change.
"""

from pathlib import Path

import pytest

from drone_sim.coverage import ApplicabilityStatus
from drone_sim.golden_path import main, render, run_golden_path
from drone_sim.graph import GapKind
from drone_sim.routing import BoundaryStatus, Decision


EXAMPLES = Path(__file__).parents[1] / "examples"
DEMO = EXAMPLES / "demo_deployment"
HYPOTHESES = EXAMPLES / "demo_hypotheses.json"


def folder_listing(root: Path) -> set[tuple[str, int]]:
    return {
        (path.relative_to(root).as_posix(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
    }


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory):
    before = folder_listing(DEMO)
    outcome = run_golden_path(DEMO, tmp_path_factory.mktemp("work"), HYPOTHESES)
    assert folder_listing(DEMO) == before, "the deployment folder must stay read-only"
    return outcome


def test_demo_folder_reconstructs_a_ready_evidence_backed_deployment(result) -> None:
    assert result.readiness.ready
    assert result.evidence is not None
    deployment = result.evidence.deployment
    assert deployment.deployment_id == "warehouse-roof-inspection-001"
    assert deployment.vehicle.mass_kg == 4.2
    assert len(deployment.mission.route.points) == 6
    assert deployment.conditions.wind_speed_mps == 6.5
    mass = result.evidence.fact("/vehicle/mass_kg").selected
    assert mass.sources[0].source_path == "aircraft/approved_current_aircraft.json"
    assert mass.sources[0].locator == "/aircraft/takeoff_mass_kg"
    assert {link.entity_type for link in result.state.entity_links} == {
        "deployment",
        "site",
        "vehicle",
    }


def test_hypothesised_mechanisms_are_applicable(result) -> None:
    applicability = {
        entry.mechanism_id: entry.applicability for entry in result.coverage.entries
    }
    for run in result.runs:
        assert applicability[run.mechanism_id] == ApplicabilityStatus.APPLIES
    assert result.first_action.hypothesis_id == "hyp_roof_clearance"


def test_energy_reserve_is_executed_and_accepted_at_analytical_fidelity(result) -> None:
    run = next(r for r in result.runs if r.hypothesis_id == "hyp_energy_reserve")
    final = run.outcome.final
    assert final.decision == Decision.ACCEPT
    assert final.providers["energy.route_demand"] == "builtin.momentum-energy@0.1.0"
    assert run.thresholds[0].threshold.value == pytest.approx(36.0)
    assert final.record.measure("reserve_breach").value is False
    assert final.record.measure("remaining_energy_wh").value > 36.0
    assert final.assessments[0].status == BoundaryStatus.CLEAR


def test_exact_mass_margin_is_currently_flagged_unquantified(result) -> None:
    # Known inconsistency recorded in docs/CURRENT_STATE.md: rule-fidelity
    # outputs carry no numeric error, so routing cannot accept them.
    run = next(r for r in result.runs if r.hypothesis_id == "hyp_takeoff_mass")
    final = run.outcome.final
    assert final.record.measure("mass_margin_kg").value == pytest.approx(1.48)
    assert final.assessments[0].status == BoundaryStatus.UNQUANTIFIED
    assert final.decision == Decision.EXHAUSTED


def test_clearance_stops_at_missing_site_geometry_provider(result) -> None:
    run = next(r for r in result.runs if r.hypothesis_id == "hyp_roof_clearance")
    plan = run.outcome.final.record.plan
    assert not plan.complete
    assert (GapKind.UNPRODUCIBLE_INPUT, "site_geometry") in {
        (gap.kind, gap.subject) for gap in plan.gaps
    }


def test_rendered_output_marks_what_is_not_implemented(result) -> None:
    text = render(result)
    assert "NOT a readiness verdict" in text
    assert "Not implemented yet" in text
    assert "hand-authored input" in text
    for artifact in result.artifacts:
        assert artifact.exists()


def test_cli_runs_the_golden_path(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "analyse",
            str(DEMO),
            "--hypotheses",
            str(HYPOTHESES),
            "--work-dir",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "status: READY" in output
    assert "routing decision: accept" in output


def test_cli_stops_at_unready_context(tmp_path: Path, capsys) -> None:
    folder = EXAMPLES / "synthetic_deployments" / "03_coastal-turbine_conflicting"

    code = main(["analyse", str(folder), "--work-dir", str(tmp_path)])

    assert code == 2
    assert "PIPELINE STOPPED" in capsys.readouterr().out


def test_cli_rejects_work_dir_inside_deployment_folder(capsys) -> None:
    code = main(["analyse", str(DEMO), "--work-dir", str(DEMO / "work")])

    assert code == 1
    assert not (DEMO / "work").exists()
