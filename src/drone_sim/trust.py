"""Model validation evidence and trust regions for registered providers.

A capability match says a provider *can* compute something. Trust says whether
its result is supported by validation evidence at this operating point, for
this model version, and for this customer or deployment. Trust is
version-specific and never inherited silently.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from drone_sim.ir import ArtifactRef, StrictModel
from drone_sim.provenance import ConfidenceLevel
from drone_sim.registry import (
    Interval,
    OperatingContext,
    Region,
    RegionStatus,
    ToolManifest,
)


class TrustScope(StrictModel):
    """Where validation evidence applies: everywhere, one customer, or one deployment."""

    kind: Literal["global", "customer", "deployment"] = "global"
    identifier: str | None = None

    @model_validator(mode="after")
    def identified(self) -> Self:
        if (self.kind == "global") != (self.identifier is None):
            raise ValueError("only non-global scopes carry an identifier")
        return self

    def applies_to(self, target: TrustScope) -> bool:
        """Global evidence applies everywhere; scoped evidence only to its scope.

        A deployment-scoped target also accepts evidence for its customer when
        the deployment identifier is prefixed ``<customer>/``.
        """

        if self.kind == "global":
            return True
        if self == target:
            return True
        return (
            self.kind == "customer"
            and target.kind == "deployment"
            and (target.identifier or "").startswith(f"{self.identifier}/")
        )


class ValidationDataset(StrictModel):
    """Evidence that a model version was compared with ground truth in a region."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    region: Region
    sample_count: int = Field(ge=1)
    scope: TrustScope = TrustScope()
    artifact: ArtifactRef | None = None
    verified: bool = Field(
        description="True when the platform reproduced the comparison, "
        "false for provider or customer attestations."
    )

    @model_validator(mode="after")
    def verified_evidence_is_pinned(self) -> Self:
        if self.verified and (self.artifact is None or self.artifact.sha256 is None):
            raise ValueError("verified datasets must reference a pinned artifact")
        return self


class ResidualStats(StrictModel):
    """Running residual (observed - predicted) statistics for one measure."""

    measure: str = Field(min_length=1)
    scope: TrustScope = TrustScope()
    count: int = Field(default=0, ge=0)
    mean: float = 0.0
    m2: float = Field(default=0.0, ge=0)
    max_abs: float = Field(default=0.0, ge=0)

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / (self.count - 1)) if self.count > 1 else math.inf

    def error_bound(self, sigma: float = 2.0) -> float:
        """Conservative absolute error: |bias| plus ``sigma`` standard deviations."""

        return abs(self.mean) + sigma * self.std

    def add(self, residual: float) -> ResidualStats:
        count = self.count + 1
        delta = residual - self.mean
        mean = self.mean + delta / count
        return self.model_copy(
            update={
                "count": count,
                "mean": mean,
                "m2": self.m2 + delta * (residual - mean),
                "max_abs": max(self.max_abs, abs(residual)),
            }
        )

    def merge(self, other: ResidualStats) -> ResidualStats:
        if other.count == 0:
            return self
        if self.count == 0:
            return other.model_copy(update={"scope": self.scope})
        count = self.count + other.count
        delta = other.mean - self.mean
        return self.model_copy(
            update={
                "count": count,
                "mean": self.mean + delta * other.count / count,
                "m2": self.m2 + other.m2 + delta**2 * self.count * other.count / count,
                "max_abs": max(self.max_abs, other.max_abs),
            }
        )


class FeedbackPoint(StrictModel):
    """One observed deployment outcome compared with the model's prediction."""

    measure: str
    predicted: float
    observed: float
    context: OperatingContext
    scope: TrustScope
    source: str = Field(min_length=1)


class ModelTrustRecord(StrictModel):
    """All validation evidence for exactly one model version."""

    model_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    datasets: tuple[ValidationDataset, ...] = ()
    residuals: tuple[ResidualStats, ...] = ()
    unsupported: tuple[Region, ...] = ()
    feedback: tuple[FeedbackPoint, ...] = ()
    drift_measures: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.model_id}@{self.version}"


class TrustLevel(StrEnum):
    VALIDATED = "validated"
    EXTRAPOLATED = "extrapolated"
    UNVALIDATED = "unvalidated"
    UNSUPPORTED = "unsupported"

    @property
    def rank(self) -> int:
        return list(TrustLevel).index(self)


class TrustPolicy(StrictModel):
    """Evidence required before a model may support a given confidence."""

    version: str = "0.1.0"
    high_confidence_samples: int = Field(default=30, ge=1)
    feedback_promotion_samples: int = Field(default=10, ge=2)
    drift_sigma: float = Field(default=4.0, gt=0)
    error_sigma: float = Field(default=2.0, gt=0)


class TrustAssessment(StrictModel):
    model_key: str
    level: TrustLevel
    max_confidence: ConfidenceLevel
    measure: str | None = None
    error_bound: float | None = None
    datasets: tuple[str, ...] = ()
    reasons: tuple[str, ...]

    @property
    def usable_for_findings(self) -> bool:
        return self.level != TrustLevel.UNSUPPORTED

    def report_note(self) -> str:
        """How a readiness report must qualify a finding from this model."""

        if self.level == TrustLevel.VALIDATED:
            return (
                f"{self.model_key} is validated here; confidence up to "
                f"{self.max_confidence.value}."
            )
        return (
            f"{self.model_key} is {self.level.value} at this operating point "
            f"({'; '.join(self.reasons)}); confidence capped at "
            f"{self.max_confidence.value}."
        )


class TrustLedger:
    """Version-specific validation evidence, updated by deployment feedback."""

    def __init__(self, policy: TrustPolicy | None = None):
        self.policy = policy or TrustPolicy()
        self._records: dict[str, ModelTrustRecord] = {}

    def record(self, record: ModelTrustRecord) -> None:
        self._records[record.key] = record

    def get(self, model_key: str) -> ModelTrustRecord | None:
        return self._records.get(model_key)

    def seed_from_manifest(self, manifest: ToolManifest) -> ModelTrustRecord:
        """Import provider-declared trust regions as unverified attestations."""

        existing = self._records.get(manifest.key) or ModelTrustRecord(
            model_id=manifest.id, version=manifest.version
        )
        declared = tuple(
            ValidationDataset(
                id=f"declared:{trust.evidence_ref}",
                description=f"Provider-declared validation {trust.evidence_ref}",
                region=trust.region,
                sample_count=trust.sample_count,
                verified=False,
            )
            for trust in manifest.trust_regions
        )
        record = existing.model_copy(update={"datasets": existing.datasets + declared})
        self.record(record)
        return record

    def assess(
        self,
        manifest: ToolManifest,
        context: OperatingContext,
        scope: TrustScope = TrustScope(),
        measure: str | None = None,
    ) -> TrustAssessment:
        base = {"model_key": manifest.key, "measure": measure}
        validity = manifest.validity_region.check(context)
        record = self._records.get(manifest.key)
        if validity.status == RegionStatus.OUTSIDE:
            return TrustAssessment(
                **base,
                level=TrustLevel.UNSUPPORTED,
                max_confidence=ConfidenceLevel.UNKNOWN,
                reasons=(f"outside claimed validity: {', '.join(validity.violated)}",),
            )
        if record is None:
            others = sorted(
                key for key in self._records if key.startswith(f"{manifest.id}@")
            )
            hint = f"; evidence exists for {', '.join(others)}" if others else ""
            return TrustAssessment(
                **base,
                level=TrustLevel.UNVALIDATED,
                max_confidence=ConfidenceLevel.LOW,
                reasons=(f"no validation evidence for version {manifest.version}{hint}",),
            )
        for region in record.unsupported:
            if region.check(context).status == RegionStatus.INSIDE:
                return TrustAssessment(
                    **base,
                    level=TrustLevel.UNSUPPORTED,
                    max_confidence=ConfidenceLevel.UNKNOWN,
                    reasons=("inside a declared unsupported extrapolation region",),
                )

        applicable = [d for d in record.datasets if d.scope.applies_to(scope)]
        covering = [
            d for d in applicable if d.region.check(context).status == RegionStatus.INSIDE
        ]
        residual = self._residuals(record, scope, measure)
        error_bound = (
            residual.error_bound(self.policy.error_sigma)
            if residual and residual.count > 1
            else None
        )
        if not covering:
            gaps = sorted(
                {
                    variable
                    for dataset in applicable
                    for variable in (
                        *dataset.region.check(context).violated,
                        *dataset.region.check(context).unknown,
                    )
                }
            )
            reason = (
                f"outside validated region: {', '.join(gaps)}"
                if gaps
                else "no validation dataset applies to this scope"
            )
            return TrustAssessment(
                **base,
                level=TrustLevel.EXTRAPOLATED,
                max_confidence=ConfidenceLevel.LOW,
                error_bound=error_bound,
                reasons=(reason,),
            )

        reasons: list[str] = []
        verified = [d for d in covering if d.verified]
        samples = residual.count if residual else 0
        if not verified:
            reasons.append("only unverified attestations cover this point")
        if measure and samples < self.policy.high_confidence_samples:
            reasons.append(
                f"{samples} residual samples for {measure} "
                f"(< {self.policy.high_confidence_samples})"
            )
        if measure and measure in record.drift_measures:
            reasons.append(f"residual drift detected for {measure}")
        confidence = ConfidenceLevel.MEDIUM if reasons else ConfidenceLevel.HIGH
        return TrustAssessment(
            **base,
            level=TrustLevel.VALIDATED,
            max_confidence=confidence,
            error_bound=error_bound,
            datasets=tuple(d.id for d in covering),
            reasons=tuple(reasons) or ("validated with sufficient verified evidence",),
        )

    def _residuals(
        self, record: ModelTrustRecord, scope: TrustScope, measure: str | None
    ) -> ResidualStats | None:
        if measure is None:
            return None
        pooled = ResidualStats(measure=measure, scope=scope)
        for stats in record.residuals:
            if stats.measure == measure and stats.scope.applies_to(scope):
                pooled = pooled.merge(stats)
        return pooled if pooled.count else None

    def record_outcome(self, model_key: str, point: FeedbackPoint) -> ModelTrustRecord:
        """Fold one real deployment outcome into the model's trust record.

        Residuals update per scope. A residual beyond ``drift_sigma`` standard
        deviations flags drift, capping confidence until reviewed. Once a scope
        accumulates ``feedback_promotion_samples`` outcomes, their bounding
        operating region becomes an unverified validation dataset for that
        scope, so trust regions grow only where real outcomes exist.
        """

        model_id, version = model_key.rsplit("@", 1)
        record = self._records.get(model_key) or ModelTrustRecord(
            model_id=model_id, version=version
        )
        residual = point.observed - point.predicted
        residuals = list(record.residuals)
        index = next(
            (
                i
                for i, stats in enumerate(residuals)
                if stats.measure == point.measure and stats.scope == point.scope
            ),
            None,
        )
        current = (
            residuals[index]
            if index is not None
            else ResidualStats(measure=point.measure, scope=point.scope)
        )
        drift = list(record.drift_measures)
        if (
            current.count >= self.policy.feedback_promotion_samples
            and abs(residual - current.mean) > self.policy.drift_sigma * current.std
            and point.measure not in drift
        ):
            drift.append(point.measure)
        updated = current.add(residual)
        if index is None:
            residuals.append(updated)
        else:
            residuals[index] = updated

        feedback = (*record.feedback, point)
        datasets = list(record.datasets)
        scoped = [
            item
            for item in feedback
            if item.scope == point.scope and item.measure == point.measure
        ]
        dataset_id = f"feedback:{point.scope.kind}:{point.scope.identifier or '*'}:{point.measure}"
        if len(scoped) >= self.policy.feedback_promotion_samples:
            datasets = [d for d in datasets if d.id != dataset_id]
            datasets.append(
                ValidationDataset(
                    id=dataset_id,
                    description=f"Deployment outcomes for {point.measure}",
                    region=_bounding_region(scoped),
                    sample_count=len(scoped),
                    scope=point.scope,
                    verified=False,
                )
            )
        record = record.model_copy(
            update={
                "residuals": tuple(residuals),
                "feedback": feedback,
                "datasets": tuple(datasets),
                "drift_measures": tuple(drift),
            }
        )
        self.record(record)
        return record


def _bounding_region(points: list[FeedbackPoint]) -> Region:
    variables = sorted(
        set.intersection(*(set(point.context.variables) for point in points))
    )
    return Region(
        bounds=tuple(
            Interval(
                variable=variable,
                minimum=min(point.context.variables[variable] for point in points),
                maximum=max(point.context.variables[variable] for point in points),
                unit="canonical",
            )
            for variable in variables
        ),
        airframes=tuple(sorted({point.context.airframe for point in points})),
    )
