"""Reviewed LLM proposals for deployment-specific applicability rules.

The model is allowed to suggest only typed predicates over Deployment IR. It
does not evaluate them or change conservative default profiles. A named human
must explicitly approve a proposal batch before deterministic evaluation uses it.
"""

from __future__ import annotations

import json

from pydantic import Field, model_validator

from drone_sim.coverage import ApplicabilityRule, MechanismProfile, default_profiles
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.ir import DeploymentIR, StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)


class ApplicabilityProposal(StrictModel):
    """One untrusted rule suggestion for one drone-taxonomy leaf."""

    mechanism_id: str
    rule: ApplicabilityRule
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def leaf_only(self) -> ApplicabilityProposal:
        if self.mechanism_id not in {
            leaf.id for leaf in DEFAULT_FAILURE_TAXONOMY.leaves()
        }:
            raise ValueError("applicability proposal must target a taxonomy leaf")
        return self


class ApplicabilityProposalBatch(StrictModel):
    """Versioned model output, deliberately separate from approved profiles."""

    contract_version: str = "0.1.0"
    taxonomy_version: str
    deployment_id: str = Field(min_length=1)
    proposals: tuple[ApplicabilityProposal, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_targets(self) -> ApplicabilityProposalBatch:
        identifiers = [proposal.mechanism_id for proposal in self.proposals]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("applicability proposals must target each mechanism once")
        return self


class ApplicabilityReview(StrictModel):
    """The explicit human control point required before rule activation."""

    operator_id: str = Field(min_length=1)
    confirmed: bool
    rationale: str = Field(min_length=1)


class ReviewedApplicabilityProfiles(StrictModel):
    """An immutable, complete profile set ready for deterministic evaluation."""

    version: str = "0.1.0"
    taxonomy_version: str
    deployment_id: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    review_rationale: str = Field(min_length=1)
    source_contract_version: str = Field(min_length=1)
    proposal_rationales: tuple[str, ...] = Field(min_length=1)
    profiles: tuple[MechanismProfile, ...] = Field(min_length=1)


def propose_applicability_rules(
    *,
    runner: StructuredOutputRunner,
    model: str,
    deployment: DeploymentIR,
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
    prompt: Prompt | None = None,
) -> ApplicabilityProposalBatch:
    """Ask the bounded LLM edge for candidate rules; do not apply them."""

    prompt = prompt or _prompt(deployment, taxonomy)
    batch, _ = runner.run(
        task=LLMTask.HYPOTHESIS_REASONING,
        model=model,
        prompt=prompt,
        contract=ApplicabilityProposalBatch,
    )
    if batch.taxonomy_version != taxonomy.version:
        raise ValueError("applicability proposal taxonomy version differs")
    if batch.deployment_id != deployment.deployment_id:
        raise ValueError("applicability proposal deployment differs")
    return batch


def approve_applicability_rules(
    batch: ApplicabilityProposalBatch,
    review: ApplicabilityReview,
    *,
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
) -> ReviewedApplicabilityProfiles:
    """Merge explicitly approved suggestions into exhaustive baseline profiles."""

    if not review.confirmed:
        raise PermissionError(
            "applicability rules require explicit operator confirmation"
        )
    if batch.taxonomy_version != taxonomy.version:
        raise ValueError("applicability proposal taxonomy version differs")
    replacements = {proposal.mechanism_id: proposal for proposal in batch.proposals}
    profiles = tuple(
        profile.model_copy(
            update={"applicability": replacements[profile.mechanism_id].rule}
        )
        if profile.mechanism_id in replacements
        else profile
        for profile in default_profiles(taxonomy)
    )
    return ReviewedApplicabilityProfiles(
        taxonomy_version=taxonomy.version,
        deployment_id=batch.deployment_id,
        reviewed_by=review.operator_id,
        review_rationale=review.rationale,
        source_contract_version=batch.contract_version,
        proposal_rationales=tuple(proposal.rationale for proposal in batch.proposals),
        profiles=profiles,
    )


def _prompt(deployment: DeploymentIR, taxonomy: FailureTaxonomy) -> Prompt:
    return Prompt(
        id="applicability-rule-proposal",
        version="1",
        messages=(
            LLMMessage(
                role=MessageRole.SYSTEM,
                content=(
                    "Propose only conservative deployment-specific applicability rules "
                    "for the supplied drone taxonomy. Rules may use canonical Deployment "
                    "IR predicates only. Do not make a readiness decision, create a test, "
                    "or set a deterministic judge threshold. The output stays untrusted "
                    "until an operator explicitly approves it."
                ),
            ),
            LLMMessage(
                role=MessageRole.USER,
                content=json.dumps(
                    {
                        "deployment": deployment.model_dump(mode="json"),
                        "taxonomy": taxonomy.model_dump(mode="json"),
                        "output_schema": ApplicabilityProposalBatch.model_json_schema(),
                    },
                    sort_keys=True,
                ),
            ),
        ),
    )
