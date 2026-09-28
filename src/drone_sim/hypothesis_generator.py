"""Grounded, contract-validated drone hypothesis generation."""

from __future__ import annotations

import json
import re
from enum import StrEnum

from pydantic import Field

from drone_sim.capabilities import (
    DEFAULT_CAPABILITY_ONTOLOGY,
    DEFAULT_MECHANISM_CAPABILITIES,
    CapabilityOntology,
    MechanismCapabilityMap,
)
from drone_sim.coverage import ApplicabilityStatus, CoverageMap
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.hypothesis import (
    FailureHypothesis,
    HypothesisGenerationContract,
    HypothesisStatus,
    SupportKind,
    merge_duplicates,
)
from drone_sim.ir import StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)
from drone_sim.provenance import EvidenceBackedDeployment, material_values


class GenerationCoverageState(StrEnum):
    COVERED = "covered"
    MISSING = "missing"
    UNMEASURABLE = "unmeasurable"


class GenerationCoverageEntry(StrictModel):
    mechanism_id: str
    state: GenerationCoverageState
    hypothesis_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)


class GroundingIssue(StrictModel):
    hypothesis_id: str
    unmeasurable_observables: tuple[str, ...] = ()
    reason: str = Field(min_length=1)


class GroundedHypothesisGeneration(StrictModel):
    contract: HypothesisGenerationContract
    coverage: tuple[GenerationCoverageEntry, ...]
    issues: tuple[GroundingIssue, ...] = ()


class HypothesisProposalBatch(StrictModel):
    """Pre-merge edge contract; duplicate proposals are intentionally allowed."""

    contract_version: str = "0.1.0"
    hypotheses: tuple[FailureHypothesis, ...]


_NUMERIC_THRESHOLD = re.compile(
    r"(?:[<>]=?|below|above|at\s+least|at\s+most|less\s+than|greater\s+than)\s*[-+]?\d",
    re.IGNORECASE,
)


def generate_hypotheses(
    *,
    runner: StructuredOutputRunner,
    model: str,
    evidence: EvidenceBackedDeployment,
    coverage: CoverageMap,
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
    ontology: CapabilityOntology = DEFAULT_CAPABILITY_ONTOLOGY,
    bindings: MechanismCapabilityMap = DEFAULT_MECHANISM_CAPABILITIES,
    prompt: Prompt | None = None,
) -> GroundedHypothesisGeneration:
    """Generate once holistically, then deterministically audit every proposal."""

    if coverage.taxonomy_version != taxonomy.version:
        raise ValueError("coverage and taxonomy versions differ")
    if bindings.validate_against(ontology, taxonomy):
        raise ValueError("capability bindings are not valid for this ontology/taxonomy")
    prompt = prompt or _prompt(evidence, coverage, taxonomy, ontology)
    batch, _ = runner.run(
        task=LLMTask.HYPOTHESIS_REASONING,
        model=model,
        prompt=prompt,
        contract=HypothesisProposalBatch,
    )
    contract = merge_duplicates(
        HypothesisGenerationContract.model_construct(
            contract_version=batch.contract_version,
            hypotheses=batch.hypotheses,
        )
    )
    issues = tuple(
        issue
        for hypothesis in contract.hypotheses
        if hypothesis.status != HypothesisStatus.MERGED
        for issue in _validate_hypothesis(
            hypothesis, evidence, ontology, bindings
        )
    )
    issue_ids = {issue.hypothesis_id for issue in issues}
    by_mechanism: dict[str, list[str]] = {}
    for hypothesis in contract.hypotheses:
        if hypothesis.status != HypothesisStatus.MERGED:
            by_mechanism.setdefault(hypothesis.mechanism_id, []).append(hypothesis.id)
    accounting = []
    for entry in coverage.entries:
        if entry.applicability == ApplicabilityStatus.RULED_OUT:
            continue
        identifiers = tuple(by_mechanism.get(entry.mechanism_id, ()))
        flagged = tuple(item for item in identifiers if item in issue_ids)
        healthy = tuple(item for item in identifiers if item not in issue_ids)
        if healthy:
            state = GenerationCoverageState.COVERED
            reason = "At least one grounded, measurable hypothesis covers this mechanism."
        elif flagged:
            state = GenerationCoverageState.UNMEASURABLE
            reason = "Generated hypotheses cite observables outside registered mechanism capabilities."
        else:
            state = GenerationCoverageState.MISSING
            reason = "The holistic generation pass returned no hypothesis for this applicable or unknown mechanism."
        accounting.append(
            GenerationCoverageEntry(
                mechanism_id=entry.mechanism_id,
                state=state,
                hypothesis_ids=identifiers,
                reason=reason,
            )
        )
    return GroundedHypothesisGeneration(
        contract=contract,
        coverage=tuple(accounting),
        issues=issues,
    )


def _validate_hypothesis(
    hypothesis: FailureHypothesis,
    evidence: EvidenceBackedDeployment,
    ontology: CapabilityOntology,
    bindings: MechanismCapabilityMap,
) -> tuple[GroundingIssue, ...]:
    document = evidence.deployment.model_dump(mode="json", exclude_none=True)
    fact_paths = {fact.path for fact in evidence.facts}
    candidate_ids = {
        candidate.id
        for fact in evidence.facts
        for candidate in (fact.selected, *fact.competing)
    }
    for variable in hypothesis.variables:
        if variable.deployment_path and not _path_exists(document, variable.deployment_path):
            raise ValueError(
                f"{hypothesis.id}: unknown deployment path {variable.deployment_path}"
            )
    evidence_refs = [
        reference
        for reference in hypothesis.supporting_references
        if reference.kind == SupportKind.DEPLOYMENT_EVIDENCE
    ]
    for reference in evidence_refs:
        if reference.reference_id not in fact_paths | candidate_ids:
            raise ValueError(
                f"{hypothesis.id}: unknown evidence reference {reference.reference_id}"
            )
    if not evidence_refs:
        raise ValueError(f"{hypothesis.id}: no deployment evidence references")
    causal_text = " ".join(hypothesis.causal_path)
    cited_values: dict[str, object] = dict(material_values(evidence.deployment))
    cited_values.update(
        {
            candidate.id: candidate.value
            for fact in evidence.facts
            for candidate in (fact.selected, *fact.competing)
        }
    )
    if not any(
        reference.reference_id in cited_values
        and str(cited_values[reference.reference_id]) in causal_text
        for reference in evidence_refs
    ):
        raise ValueError(
            f"{hypothesis.id}: causal reasoning is generic; include a cited deployment value"
        )
    for condition in (*hypothesis.confirm_if, *hypothesis.falsify_if):
        if _NUMERIC_THRESHOLD.search(condition.description):
            raise ValueError(
                f"{hypothesis.id}: numeric decision thresholds belong to deterministic judges"
            )
    binding = bindings.binding(hypothesis.mechanism_id)
    measurable = {
        measure
        for capability_id in binding.required
        for measure in ontology.get(capability_id).measures
    }
    requested = {
        condition.observable
        for condition in (*hypothesis.confirm_if, *hypothesis.falsify_if)
    }
    missing = tuple(sorted(requested - measurable))
    if not missing:
        return ()
    return (
        GroundingIssue(
            hypothesis_id=hypothesis.id,
            unmeasurable_observables=missing,
            reason="No capability bound to this mechanism emits the requested observable.",
        ),
    )


def _path_exists(document: object, path: str) -> bool:
    value = document
    for encoded in path.removeprefix("/").split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]  # type: ignore[index]
        except (IndexError, KeyError, TypeError, ValueError):
            return False
    return True


def _prompt(
    evidence: EvidenceBackedDeployment,
    coverage: CoverageMap,
    taxonomy: FailureTaxonomy,
    ontology: CapabilityOntology,
) -> Prompt:
    return Prompt(
        id="hypothesis-generation",
        version="2",
        messages=(
            LLMMessage(
                role=MessageRole.SYSTEM,
                content=(
                    "Generate deployment-specific drone failure hypotheses. Use no numeric "
                    "decision thresholds. Cite only supplied evidence paths/candidate IDs and "
                    "use observables from the supplied capability ontology."
                ),
            ),
            LLMMessage(
                role=MessageRole.USER,
                content=json.dumps(
                    {
                        "evidence": evidence.model_dump(mode="json"),
                        "coverage": coverage.model_dump(mode="json"),
                        "taxonomy": taxonomy.model_dump(mode="json"),
                        "capability_ontology": ontology.model_dump(mode="json"),
                        "output_schema": HypothesisProposalBatch.model_json_schema(),
                    },
                    sort_keys=True,
                ),
            ),
        ),
    )
