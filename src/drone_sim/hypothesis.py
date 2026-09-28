"""Typed, falsifiable drone failure hypotheses for downstream test planning."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from drone_sim.coverage import Materiality, Testability
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.ir import StrictModel


class HypothesisUncertainty(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    MERGED = "merged"
    REJECTED = "rejected"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class SupportKind(StrEnum):
    DEPLOYMENT_EVIDENCE = "deployment_evidence"
    TAXONOMY = "taxonomy"
    INTERNAL_KNOWLEDGE = "internal_knowledge"
    EXTERNAL_KNOWLEDGE = "external_knowledge"


class SupportingReference(StrictModel):
    kind: SupportKind
    reference_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class HypothesisVariable(StrictModel):
    name: str = Field(min_length=1)
    deployment_path: str | None = Field(default=None, pattern=r"^/")
    role: str = Field(min_length=1)


class ObservationCondition(StrictModel):
    """Qualitative condition only; deterministic judges bind numeric thresholds."""

    description: str = Field(min_length=1)
    observable: str = Field(min_length=1)


class FailureHypothesis(StrictModel):
    id: str = Field(pattern=r"^hyp_[a-z0-9_]+$")
    mechanism_id: str
    affected_target: str = Field(min_length=1)
    variables: tuple[HypothesisVariable, ...] = Field(min_length=1)
    causal_path: tuple[str, ...] = Field(min_length=2)
    supporting_references: tuple[SupportingReference, ...] = Field(min_length=1)
    uncertainty: HypothesisUncertainty
    uncertainty_reason: str = Field(min_length=1)
    materiality: Materiality
    candidate_testabilities: tuple[Testability, ...] = Field(min_length=1)
    confirm_if: tuple[ObservationCondition, ...] = Field(min_length=1)
    falsify_if: tuple[ObservationCondition, ...] = Field(min_length=1)
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    merged_into: str | None = Field(default=None, pattern=r"^hyp_[a-z0-9_]+$")

    @model_validator(mode="after")
    def is_testable_and_grounded(self) -> FailureHypothesis:
        if self.mechanism_id not in {
            leaf.id for leaf in DEFAULT_FAILURE_TAXONOMY.leaves()
        }:
            raise ValueError("mechanism_id must be a taxonomy leaf")
        if self.status == HypothesisStatus.MERGED and not self.merged_into:
            raise ValueError("merged hypotheses require merged_into")
        if self.status != HypothesisStatus.MERGED and self.merged_into:
            raise ValueError("merged_into is only valid for merged hypotheses")
        if not any(
            ref.kind == SupportKind.DEPLOYMENT_EVIDENCE
            for ref in self.supporting_references
        ):
            raise ValueError("hypotheses require deployment evidence support")
        return self

    @property
    def duplicate_key(self) -> tuple[str, str, tuple[str, ...]]:
        return (
            self.mechanism_id,
            self.affected_target.casefold(),
            tuple(sorted(variable.name.casefold() for variable in self.variables)),
        )


class HypothesisGenerationContract(StrictModel):
    """The only accepted LLM/knowledge-agent output boundary for hypotheses."""

    contract_version: str = "0.1.0"
    hypotheses: tuple[FailureHypothesis, ...]

    @model_validator(mode="after")
    def ids_and_duplicates_are_explicit(self) -> HypothesisGenerationContract:
        identifiers = [hypothesis.id for hypothesis in self.hypotheses]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("hypothesis IDs must be unique")
        active = [
            hypothesis
            for hypothesis in self.hypotheses
            if hypothesis.status != HypothesisStatus.MERGED
        ]
        keys = [hypothesis.duplicate_key for hypothesis in active]
        if len(keys) != len(set(keys)):
            raise ValueError("overlapping active hypotheses must be merged explicitly")
        return self


def merge_duplicates(
    contract: HypothesisGenerationContract,
) -> HypothesisGenerationContract:
    """Mark duplicate proposals merged while retaining their source evidence."""
    canonical: dict[tuple[str, str, tuple[str, ...]], str] = {}
    merged: list[FailureHypothesis] = []
    for hypothesis in contract.hypotheses:
        existing = canonical.get(hypothesis.duplicate_key)
        if existing is None:
            canonical[hypothesis.duplicate_key] = hypothesis.id
            merged.append(hypothesis)
        else:
            merged.append(
                hypothesis.model_copy(
                    update={"status": HypothesisStatus.MERGED, "merged_into": existing}
                )
            )
    return HypothesisGenerationContract(hypotheses=tuple(merged))
