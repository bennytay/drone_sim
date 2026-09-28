"""Drone deployment verification primitives."""

from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.ir import DeploymentIR
from drone_sim.provenance import EvidenceBackedDeployment
from drone_sim.validation import ReadinessReport

__all__ = [
    "DEFAULT_FAILURE_TAXONOMY",
    "DeploymentIR",
    "EvidenceBackedDeployment",
    "FailureTaxonomy",
    "ReadinessReport",
]
