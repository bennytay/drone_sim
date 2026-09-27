"""Deterministic completeness and conflict checks for drone deployments."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, ValidationError

from drone_sim.ir import DeploymentIR, StrictModel
from drone_sim.provenance import (
    ConfidenceLevel,
    EvidenceBackedDeployment,
    ValueOrigin,
)


class ReadinessStatus(StrEnum):
    READY = "ready"
    INCOMPLETE = "incomplete"
    UNCERTAIN = "uncertain"
    CONFLICTING = "conflicting"
    INVALID = "invalid"


class FindingCode(StrEnum):
    MISSING_DEPENDENCY = "missing_dependency"
    UNCERTAIN_VALUE = "uncertain_value"
    CONFLICTING_VALUES = "conflicting_values"
    INVALID_VALUE = "invalid_value"


class Dependency(StrictModel):
    """Context needed by one class of deterministic evaluation."""

    path: str = Field(pattern=r"^/")
    description: str = Field(min_length=1)
    prefix: bool = False
    minimum_confidence: ConfidenceLevel = ConfidenceLevel.LOW
    accepted_approximate_origins: tuple[ValueOrigin, ...] = ()


class EvaluationProfile(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    dependencies: tuple[Dependency, ...] = Field(min_length=1)


class ValidationFinding(StrictModel):
    code: FindingCode
    path: str = Field(pattern=r"^/")
    message: str = Field(min_length=1)
    candidate_ids: tuple[str, ...] = ()


class ReadinessReport(StrictModel):
    profile_id: str = Field(min_length=1)
    status: ReadinessStatus
    resolved_dependencies: tuple[str, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == ReadinessStatus.READY

    @property
    def unresolved_paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(finding.path for finding in self.findings))


HYPOTHESIS_GENERATION_PROFILE = EvaluationProfile(
    id="drone_hypothesis_generation_v1",
    description="Minimum context needed to propose grounded drone failure hypotheses",
    dependencies=(
        Dependency(path="/deployment_id", description="Deployment identity"),
        Dependency(path="/vehicle/airframe", description="Drone airframe type"),
        Dependency(path="/vehicle/mass_kg", description="Flight mass"),
        Dependency(path="/mission/objective", description="Mission objective"),
        Dependency(
            path="/mission/route/points",
            description="Planned drone route",
            prefix=True,
        ),
        Dependency(path="/site/name", description="Operating site"),
        Dependency(path="/autonomy/mode", description="Autonomy mode"),
        Dependency(
            path="/success_criteria",
            description="Deployment success criteria",
            prefix=True,
        ),
    ),
)


_CONFIDENCE_RANK = {
    ConfidenceLevel.UNKNOWN: 0,
    ConfidenceLevel.LOW: 1,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.HIGH: 3,
}

_NON_CANONICAL_UNITS = {
    "ft": "m",
    "feet": "m",
    "lb": "kg",
    "lbs": "kg",
    "mph": "m/s",
    "km/h": "m/s",
    "kph": "m/s",
    "kt": "m/s",
    "kts": "m/s",
    "knot": "m/s",
    "knots": "m/s",
}


def assess_evidence(
    evidence: EvidenceBackedDeployment,
    profile: EvaluationProfile = HYPOTHESIS_GENERATION_PROFILE,
) -> ReadinessReport:
    """Assess whether evidence crosses a profile's explicit readiness threshold."""

    facts = {fact.path: fact for fact in evidence.facts}
    findings: list[ValidationFinding] = []
    resolved: list[str] = []

    for dependency in profile.dependencies:
        matches = [
            fact
            for path, fact in facts.items()
            if path == dependency.path
            or (dependency.prefix and path.startswith(f"{dependency.path}/"))
        ]
        if not matches:
            findings.append(
                ValidationFinding(
                    code=FindingCode.MISSING_DEPENDENCY,
                    path=dependency.path,
                    message=dependency.description,
                )
            )
            continue
        resolved.append(dependency.path)
        for fact in matches:
            selected = fact.selected
            approximate = selected.origin in {
                ValueOrigin.INFERRED,
                ValueOrigin.ESTIMATED,
                ValueOrigin.MODEL_DERIVED,
                ValueOrigin.ASSUMED,
            }
            below_threshold = (
                _CONFIDENCE_RANK[selected.uncertainty.confidence]
                < _CONFIDENCE_RANK[dependency.minimum_confidence]
            )
            disallowed_approximation = (
                approximate
                and selected.origin not in dependency.accepted_approximate_origins
            )
            if below_threshold or disallowed_approximation:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.UNCERTAIN_VALUE,
                        path=fact.path,
                        message=(
                            f"{selected.origin.value} value at "
                            f"{selected.uncertainty.confidence.value} confidence does "
                            "not meet the evaluation dependency"
                        ),
                        candidate_ids=(selected.id,),
                    )
                )

    for fact in evidence.facts:
        if fact.competing and fact.resolution is None:
            findings.append(
                ValidationFinding(
                    code=FindingCode.CONFLICTING_VALUES,
                    path=fact.path,
                    message="Contradictory candidates require explicit resolution",
                    candidate_ids=(
                        fact.selected.id,
                        *(candidate.id for candidate in fact.competing),
                    ),
                )
            )
        if fact.path.endswith("/unit") and isinstance(fact.selected.value, str):
            canonical = _NON_CANONICAL_UNITS.get(fact.selected.value.lower())
            if canonical:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.INVALID_VALUE,
                        path=fact.path,
                        message=(
                            f"Non-canonical unit {fact.selected.value!r}; source "
                            f"adapter must convert the value to {canonical!r}"
                        ),
                        candidate_ids=(fact.selected.id,),
                    )
                )

    return ReadinessReport(
        profile_id=profile.id,
        status=_status(findings),
        resolved_dependencies=tuple(resolved),
        findings=tuple(findings),
    )


def assess_values(
    values: dict[str, Any],
    profile: EvaluationProfile = HYPOTHESIS_GENERATION_PROFILE,
) -> ReadinessReport:
    """Report missing or invalid input before an evidence envelope can exist."""

    findings: list[ValidationFinding] = []
    present_top_levels = set(values)
    resolved: list[str] = []
    for dependency in profile.dependencies:
        top_level = dependency.path.split("/", 2)[1]
        if top_level in present_top_levels:
            resolved.append(dependency.path)
        else:
            findings.append(
                ValidationFinding(
                    code=FindingCode.MISSING_DEPENDENCY,
                    path=dependency.path,
                    message=dependency.description,
                )
            )
    if findings:
        return ReadinessReport(
            profile_id=profile.id,
            status=ReadinessStatus.INCOMPLETE,
            resolved_dependencies=tuple(resolved),
            findings=tuple(findings),
        )

    try:
        DeploymentIR.model_validate(values)
    except ValidationError as error:
        for detail in error.errors(include_url=False):
            path = "/" + "/".join(str(part) for part in detail["loc"])
            code = (
                FindingCode.MISSING_DEPENDENCY
                if detail["type"] == "missing"
                else FindingCode.INVALID_VALUE
            )
            findings.append(
                ValidationFinding(
                    code=code,
                    path=path,
                    message=detail["msg"],
                )
            )
    return ReadinessReport(
        profile_id=profile.id,
        status=_status(findings),
        resolved_dependencies=tuple(resolved),
        findings=tuple(findings),
    )


def _status(findings: list[ValidationFinding]) -> ReadinessStatus:
    codes = {finding.code for finding in findings}
    if FindingCode.INVALID_VALUE in codes:
        return ReadinessStatus.INVALID
    if FindingCode.MISSING_DEPENDENCY in codes:
        return ReadinessStatus.INCOMPLETE
    if FindingCode.CONFLICTING_VALUES in codes:
        return ReadinessStatus.CONFLICTING
    if FindingCode.UNCERTAIN_VALUE in codes:
        return ReadinessStatus.UNCERTAIN
    return ReadinessStatus.READY
