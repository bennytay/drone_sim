"""Fidelity routing: cheapest credible provider first, justified escalation.

The router plans a goal at the lowest fidelity the failure mechanism allows,
executes it, and checks each decision measure against its threshold. It
escalates the producing capability to the next fidelity class when the result
is near the decision boundary, unquantified, missing, or produced where the
provider's validity cannot be confirmed. Every choice and escalation carries a
written justification, and disagreement between fidelity levels is flagged
for review rather than silently resolved.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, Field

from drone_sim.capabilities import (
    DEFAULT_MECHANISM_CAPABILITIES,
    Capability,
    CapabilityKind,
    DataKind,
    MechanismCapabilityMap,
)
from drone_sim.graph import (
    EvaluationGoal,
    EvidenceMeasure,
    ExecutionPlan,
    ExecutionRecord,
    GraphPlanner,
    execute,
)
from drone_sim.interfaces import ToolAdapter
from drone_sim.ir import StrictModel
from drone_sim.provenance import ConfidenceLevel
from drone_sim.registry import (
    FidelityClass,
    OperatingContext,
    ProviderOption,
    RegionStatus,
    ToolRegistry,
)
from drone_sim.trust import TrustLedger, TrustLevel, TrustScope


class FidelityFloor(StrictModel):
    """Minimum fidelity a mechanism requires for one capability, and why."""

    capability_id: str
    minimum: FidelityClass
    reason: str = Field(min_length=1)


_SENSOR_REALISM = (
    "environment_weather.visibility.degradation",
    "navigation_localization.relative.feature_poor",
    "perception_sensing.observability.material",
    "perception_sensing.integrity.occlusion_contamination",
)


class RoutingPolicy(StrictModel):
    """Versioned rules for minimum fidelity and escalation."""

    version: str = "0.1.0"
    boundary_factor: float = Field(default=2.0, gt=0)
    sensor_realism_mechanisms: tuple[str, ...] = _SENSOR_REALISM
    mechanism_floors: dict[str, tuple[FidelityFloor, ...]] = Field(default_factory=dict)

    def floors(
        self, goal: EvaluationGoal, capabilities: Mapping[str, Capability]
    ) -> dict[str, FidelityFloor]:
        """Mechanism-driven minimum fidelity for each capability.

        Closed-loop composites always need a closed-loop simulator. Sensor
        observation synthesis needs rendered sensors when the mechanism's
        outcome depends on appearance. Everything else starts at the cheapest
        class and escalates only on evidence.
        """

        floors: dict[str, FidelityFloor] = {}
        for capability in capabilities.values():
            if capability.kind == CapabilityKind.COMPOSITE and capability.closed_loop:
                floors[capability.id] = FidelityFloor(
                    capability_id=capability.id,
                    minimum=FidelityClass.HIGH_FIDELITY_SIMULATION,
                    reason="closed-loop interaction between autonomy, dynamics, and sensing",
                )
        if goal.mechanism_id in self.sensor_realism_mechanisms:
            floors["sensing.observation_synthesis"] = FidelityFloor(
                capability_id="sensing.observation_synthesis",
                minimum=FidelityClass.HIGH_FIDELITY_SIMULATION,
                reason="mechanism outcome depends on rendered sensor appearance",
            )
        for floor in self.mechanism_floors.get(goal.mechanism_id or "", ()):
            floors[floor.capability_id] = floor
        return floors


class Comparator(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


class DecisionThreshold(StrictModel):
    """Threshold a deterministic judge will apply; routing only uses its margin."""

    measure: str = Field(min_length=1)
    comparator: Comparator
    value: float
    unit: str | None = None

    def margin(self, observed: float) -> float:
        """Signed distance to the threshold; positive is the satisfying side."""

        if self.comparator in {Comparator.GT, Comparator.GTE}:
            return observed - self.value
        return self.value - observed


class BoundaryStatus(StrEnum):
    CLEAR = "clear"
    NEAR_BOUNDARY = "near_boundary"
    UNQUANTIFIED = "unquantified"
    VALIDITY_UNCONFIRMED = "validity_unconfirmed"
    UNTRUSTED = "untrusted"
    MISSING = "missing"


class BoundaryAssessment(StrictModel):
    measure: str
    status: BoundaryStatus
    node_id: str | None = None
    provider_key: str | None = None
    fidelity: FidelityClass | None = None
    margin: float | None = None
    error: float | None = None
    trust: TrustLevel | None = None
    max_confidence: ConfidenceLevel | None = None
    reason: str


class Decision(StrEnum):
    ACCEPT = "accept"
    ESCALATE = "escalate"
    EXHAUSTED = "exhausted"


class RoutingStep(StrictModel):
    """One planned and executed fidelity level with its justification."""

    level: int = Field(ge=0)
    floors: dict[str, FidelityClass]
    providers: dict[str, str]
    selection: tuple[str, ...]
    assessments: tuple[BoundaryAssessment, ...]
    decision: Decision
    justification: tuple[str, ...]
    record: ExecutionRecord


class Disagreement(StrictModel):
    measure: str
    lower: EvidenceMeasure
    higher: EvidenceMeasure
    difference: float
    tolerance: float


class RoutingOutcome(StrictModel):
    policy_version: str
    goal: EvaluationGoal
    steps: tuple[RoutingStep, ...] = Field(min_length=1)
    disagreements: tuple[Disagreement, ...] = ()

    @property
    def final(self) -> RoutingStep:
        return self.steps[-1]

    @property
    def requires_review(self) -> bool:
        return bool(self.disagreements) or self.final.decision != Decision.ACCEPT


def _error_width(evidence: EvidenceMeasure) -> float | None:
    """Half-width of the declared error: a bound, or one standard deviation."""

    return None if evidence.error is None else evidence.error.value


class FidelityRouter:
    def __init__(
        self,
        registry: ToolRegistry,
        tools: Mapping[str, ToolAdapter],
        policy: RoutingPolicy | None = None,
        bindings: MechanismCapabilityMap = DEFAULT_MECHANISM_CAPABILITIES,
        trust: TrustLedger | None = None,
    ):
        self.registry = registry
        self.tools = tools
        self.policy = policy or RoutingPolicy()
        self.bindings = bindings
        self.trust = trust

    def investigate(
        self,
        goal: EvaluationGoal,
        context: OperatingContext,
        thresholds: tuple[DecisionThreshold, ...],
        initial: Mapping[DataKind, BaseModel],
        max_levels: int = 6,
        scope: TrustScope = TrustScope(),
    ) -> RoutingOutcome:
        self._scope = scope
        capabilities = {c.id: c for c in self.registry.ontology.capabilities}
        mechanism_floors = self.policy.floors(goal, capabilities)
        floors = {cid: floor.minimum for cid, floor in mechanism_floors.items()}
        steps: list[RoutingStep] = []
        for level in range(max_levels):
            selection: list[str] = []
            plan = GraphPlanner(
                self.registry,
                self.bindings,
                self._selector(floors, mechanism_floors, selection, context),
            ).plan(goal, context)
            record = execute(plan, self.tools, initial)
            assessments = tuple(
                self._assess(threshold, record, plan, context) for threshold in thresholds
            )
            decision, justification, raised = self._decide(
                plan, assessments, floors, context
            )
            steps.append(
                RoutingStep(
                    level=level,
                    floors=dict(floors),
                    providers={node.capability_id: node.provider_key for node in plan.nodes},
                    selection=tuple(selection),
                    assessments=assessments,
                    decision=decision,
                    justification=justification,
                    record=record,
                )
            )
            if decision != Decision.ESCALATE:
                break
            floors.update(raised)
        return RoutingOutcome(
            policy_version=self.policy.version,
            goal=goal,
            steps=tuple(steps),
            disagreements=self._disagreements(steps),
        )

    def _selector(
        self,
        floors: Mapping[str, FidelityClass],
        mechanism_floors: Mapping[str, FidelityFloor],
        selection: list[str],
        context: OperatingContext,
    ):
        def select(
            capability: Capability, options: tuple[ProviderOption, ...]
        ) -> ProviderOption | None:
            floor = floors.get(capability.id, FidelityClass.RULE)
            trust = {option.manifest_key: self._trust(option.manifest_key, context) for option in options}
            eligible = [
                option
                for option in options
                if option.usable
                and option.fidelity.rank >= floor.rank
                and trust[option.manifest_key] != TrustLevel.UNSUPPORTED
            ]
            eligible.sort(
                key=lambda option: (
                    option.fidelity.rank,
                    trust[option.manifest_key].rank if trust[option.manifest_key] else 0,
                    option.validity.status != RegionStatus.INSIDE,
                    option.cost.rank,
                    option.typical_runtime_s,
                    option.manifest_key,
                )
            )
            chosen = eligible[0] if eligible else None
            if chosen is None:
                return None
            if capability.id in mechanism_floors and floor == mechanism_floors[capability.id].minimum:
                why = f"mechanism requires {floor.value}: {mechanism_floors[capability.id].reason}"
            elif floor.rank > 0:
                why = f"escalated to at least {floor.value}"
            else:
                why = "cheapest usable provider"
            skipped = [
                option.manifest_key
                for option in options
                if option.usable and option.fidelity.rank < floor.rank
            ]
            detail = f"; bypassed lower fidelity {', '.join(skipped)}" if skipped else ""
            level = trust[chosen.manifest_key]
            if level is not None:
                less_trusted = [
                    option.manifest_key
                    for option in eligible[1:]
                    if option.fidelity == chosen.fidelity
                    and trust[option.manifest_key].rank > level.rank
                ]
                detail += f"; trust {level.value}"
                if less_trusted:
                    detail += f", preferred over less-trusted {', '.join(less_trusted)}"
            selection.append(
                f"{capability.id} -> {chosen.manifest_key} "
                f"({chosen.fidelity.value}, {chosen.cost.value}): {why}{detail}"
            )
            return chosen

        return select

    def _trust(self, manifest_key: str, context: OperatingContext) -> TrustLevel | None:
        if self.trust is None:
            return None
        return self.trust.assess(self.registry.get(manifest_key), context, self._scope).level

    def _assess(
        self,
        threshold: DecisionThreshold,
        record: ExecutionRecord,
        plan: ExecutionPlan,
        context: OperatingContext,
    ) -> BoundaryAssessment:
        node_id = plan.measure_sources.get(threshold.measure)
        evidence = next(
            (item for item in record.evidence if item.name == threshold.measure), None
        )
        if node_id is None or evidence is None or isinstance(evidence.value, bool):
            return BoundaryAssessment(
                measure=threshold.measure,
                status=BoundaryStatus.MISSING,
                node_id=node_id,
                reason="no numeric evidence was produced for the decision measure",
            )
        node = plan.node(node_id)
        fidelity = self.registry.get(node.provider_key).fidelity
        base = {
            "measure": threshold.measure,
            "node_id": node_id,
            "provider_key": node.provider_key,
            "fidelity": fidelity,
            "margin": threshold.margin(evidence.value),
        }
        option = next(
            option
            for option in self.registry.options(node.capability_id, context)
            if option.manifest_key == node.provider_key
        )
        if option.validity.status == RegionStatus.UNKNOWN:
            return BoundaryAssessment(
                **base,
                status=BoundaryStatus.VALIDITY_UNCONFIRMED,
                reason=(
                    "provider validity cannot be confirmed without "
                    f"{', '.join(option.validity.unknown)}"
                ),
            )
        width = _error_width(evidence)
        if self.trust is not None:
            trust = self.trust.assess(
                self.registry.get(node.provider_key), context, self._scope, threshold.measure
            )
            base["trust"] = trust.level
            base["max_confidence"] = trust.max_confidence
            if trust.error_bound is not None and math.isfinite(trust.error_bound):
                width = max(width or 0.0, trust.error_bound)
            if trust.level != TrustLevel.VALIDATED:
                return BoundaryAssessment(
                    **base,
                    status=BoundaryStatus.UNTRUSTED,
                    error=width,
                    reason=f"{trust.level.value} model: {'; '.join(trust.reasons)}",
                )
        if width is None or not evidence.fully_quantified:
            return BoundaryAssessment(
                **base,
                status=BoundaryStatus.UNQUANTIFIED,
                error=width,
                reason="result or an upstream contributor has no declared error",
            )
        margin = base["margin"]
        band = self.policy.boundary_factor * width
        if abs(margin) <= band:
            return BoundaryAssessment(
                **base,
                status=BoundaryStatus.NEAR_BOUNDARY,
                error=width,
                reason=(
                    f"margin {margin:.3g} is within {self.policy.boundary_factor:g}x "
                    f"error ({band:.3g}) of the threshold"
                ),
            )
        return BoundaryAssessment(
            **base,
            status=BoundaryStatus.CLEAR,
            error=width,
            reason=f"margin {margin:.3g} exceeds the {band:.3g} boundary band",
        )

    def _decide(
        self,
        plan: ExecutionPlan,
        assessments: tuple[BoundaryAssessment, ...],
        floors: Mapping[str, FidelityClass],
        context: OperatingContext,
    ) -> tuple[Decision, tuple[str, ...], dict[str, FidelityClass]]:
        justification: list[str] = []
        raised: dict[str, FidelityClass] = {}
        unresolved = False
        if not plan.complete:
            justification.extend(f"gap {gap.subject}: {gap.reason}" for gap in plan.gaps)
        for assessment in assessments:
            if assessment.status == BoundaryStatus.CLEAR:
                justification.append(
                    f"{assessment.measure}: accepted at {assessment.fidelity.value} "
                    f"via {assessment.provider_key}; {assessment.reason}"
                )
                continue
            unresolved = True
            if assessment.node_id is None or assessment.fidelity is None:
                justification.append(f"{assessment.measure}: {assessment.reason}")
                continue
            capability_id = plan.node(assessment.node_id).capability_id
            higher = [
                option
                for option in self.registry.options(capability_id, context)
                if option.usable and option.fidelity.rank > assessment.fidelity.rank
            ]
            if not higher:
                justification.append(
                    f"{assessment.measure}: {assessment.reason}; no higher-fidelity "
                    f"provider for {capability_id}"
                )
                continue
            target = min(higher, key=lambda option: option.fidelity.rank).fidelity
            if target.rank > floors.get(capability_id, FidelityClass.RULE).rank:
                raised[capability_id] = target
            justification.append(
                f"{assessment.measure}: {assessment.reason}; escalating "
                f"{capability_id} from {assessment.fidelity.value} to {target.value}"
            )
        if raised:
            return Decision.ESCALATE, tuple(justification), raised
        if unresolved or not plan.complete:
            return Decision.EXHAUSTED, tuple(justification), raised
        return Decision.ACCEPT, tuple(justification), raised

    def _disagreements(self, steps: list[RoutingStep]) -> tuple[Disagreement, ...]:
        """Compare each executed level with the next higher level.

        Results disagree when their difference exceeds the sum of their error
        widths. The higher-fidelity result is not assumed correct: the
        disagreement is recorded so a reviewer or trust tracking can act.
        """

        found: list[Disagreement] = []
        for lower_step, higher_step in zip(steps, steps[1:]):
            for lower in lower_step.record.evidence:
                higher = next(
                    (m for m in higher_step.record.evidence if m.name == lower.name),
                    None,
                )
                if (
                    higher is None
                    or higher.provider_key == lower.provider_key
                    or isinstance(lower.value, bool)
                    or isinstance(higher.value, bool)
                ):
                    continue
                tolerance = (_error_width(lower) or 0.0) + (_error_width(higher) or 0.0)
                difference = abs(float(lower.value) - float(higher.value))
                if difference > tolerance:
                    found.append(
                        Disagreement(
                            measure=lower.name,
                            lower=lower,
                            higher=higher,
                            difference=difference,
                            tolerance=tolerance,
                        )
                    )
        return tuple(found)

