"""Drone deployment verification primitives."""

from drone_sim.capabilities import (
    DEFAULT_CAPABILITY_ONTOLOGY,
    DEFAULT_MECHANISM_CAPABILITIES,
    CapabilityOntology,
)
from drone_sim.coverage import CoverageMap, assess_coverage
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.hypothesis import FailureHypothesis, HypothesisGenerationContract
from drone_sim.ir import DeploymentIR
from drone_sim.provenance import EvidenceBackedDeployment
from drone_sim.registry import ToolManifest, ToolRegistry
from drone_sim.validation import ReadinessReport

__all__ = [
    "DEFAULT_CAPABILITY_ONTOLOGY",
    "DEFAULT_MECHANISM_CAPABILITIES",
    "DEFAULT_FAILURE_TAXONOMY",
    "CapabilityOntology",
    "CoverageMap",
    "DeploymentIR",
    "EvidenceBackedDeployment",
    "FailureHypothesis",
    "FailureTaxonomy",
    "HypothesisGenerationContract",
    "ReadinessReport",
    "ToolManifest",
    "ToolRegistry",
    "assess_coverage",
]
