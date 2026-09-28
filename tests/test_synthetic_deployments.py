import json
from pathlib import Path

import pytest

from drone_sim.context import ContextOrchestrator


CORPUS = Path(__file__).parents[1] / "examples" / "synthetic_deployments"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text())


@pytest.mark.parametrize(
    ("folder_name", "expected"),
    [
        (entry["folder"], entry["expected_readiness"])
        for entry in MANIFEST["deployments"]
    ],
)
def test_synthetic_deployment_readiness(
    tmp_path: Path, folder_name: str, expected: str
) -> None:
    orchestrator = ContextOrchestrator(
        CORPUS / folder_name,
        tmp_path / f"{folder_name}.state.json",
    )

    _, state = orchestrator.run()
    report = orchestrator.assess(state)

    assert report.status == expected


def test_site_model_metadata_is_not_used_as_canonical_site(tmp_path: Path) -> None:
    folder = CORPUS / "05_bridge-inspection_split"
    orchestrator = ContextOrchestrator(folder, tmp_path / "split.state.json")

    evidence, state = orchestrator.run()

    assert evidence is not None
    assert evidence.deployment.site.name == "Hawkesbury bridge"
    assert state.candidates["site"][0].source_path == "box-d/d.json"
