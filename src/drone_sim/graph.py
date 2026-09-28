"""Deterministic capability-graph planning and execution.

An agent chooses *what* to evaluate: a hypothesis or a set of measures. The
planner deterministically expands that goal backwards into capabilities, binds
registered providers, validates every edge, and orders the graph. The runtime
executes it and records provenance and uncertainty sources for every measure.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from drone_sim.capabilities import (
    DEFAULT_MECHANISM_CAPABILITIES,
    Capability,
    DataKind,
    MechanismCapabilityMap,
)
from drone_sim.hypothesis import FailureHypothesis
from drone_sim.interfaces import MeasureError, MeasureSet, ToolAdapter
from drone_sim.ir import StrictModel
from drone_sim.registry import (
    FidelityClass,
    OperatingContext,
    ProviderOption,
    ToolRegistry,
    UncertaintyKind,
)

INITIAL = "initial"


class EvaluationGoal(StrictModel):
    """Measures an evaluation must produce, optionally scoped to a mechanism."""

    measures: tuple[str, ...] = Field(min_length=1)
    mechanism_id: str | None = None
    hypothesis_id: str | None = None

    @classmethod
    def for_hypothesis(cls, hypothesis: FailureHypothesis) -> Self:
        observables = dict.fromkeys(
            condition.observable
            for condition in (*hypothesis.confirm_if, *hypothesis.falsify_if)
        )
        return cls(
            measures=tuple(observables),
            mechanism_id=hypothesis.mechanism_id,
            hypothesis_id=hypothesis.id,
        )


class Edge(StrictModel):
    """Connects a producer's output (or an initial value) to an input port."""

    port: str
    kind: DataKind
    source: str


class PlanNode(StrictModel):
    id: str
    capability_id: str
    provider_key: str
    inputs: tuple[Edge, ...]
    produces: tuple[DataKind, ...]
    measures: tuple[str, ...]
    alternatives: tuple[str, ...] = ()


class GapKind(StrEnum):
    UNMEASURABLE = "unmeasurable"
    NO_PROVIDER = "no_provider"
    UNPRODUCIBLE_INPUT = "unproducible_input"


class PlanGap(StrictModel):
    """A goal element the registry cannot satisfy, with the reason."""

    kind: GapKind
    subject: str
    reason: str


class ExecutionPlan(StrictModel):
    goal: EvaluationGoal
    context: OperatingContext
    nodes: tuple[PlanNode, ...]
    measure_sources: dict[str, str] = Field(default_factory=dict)
    gaps: tuple[PlanGap, ...] = ()

    @model_validator(mode="after")
    def topologically_ordered(self) -> Self:
        seen = {INITIAL}
        for node in self.nodes:
            unknown = {edge.source for edge in node.inputs} - seen
            if unknown:
                raise ValueError(f"{node.id} depends on unplanned nodes {sorted(unknown)}")
            seen.add(node.id)
        missing = set(self.measure_sources.values()) - seen
        if missing:
            raise ValueError("measure sources must be planned nodes")
        return self

    @property
    def complete(self) -> bool:
        return not self.gaps

    def node(self, node_id: str) -> PlanNode:
        return next(node for node in self.nodes if node.id == node_id)


Selector = Callable[[Capability, tuple[ProviderOption, ...]], ProviderOption | None]


def cheapest_usable(
    capability: Capability, options: tuple[ProviderOption, ...]
) -> ProviderOption | None:
    """Default selector: the registry's first usable option."""

    return next((option for option in options if option.usable), None)


class _Unsatisfiable(Exception):
    def __init__(self, gap: PlanGap):
        self.gap = gap


class GraphPlanner:
    """Backward-chaining planner over the ontology and a provider registry.

    Measures are resolved to capabilities, preferring the mechanism binding.
    Each capability is bound to one provider; the provider's own input ports
    (not the capability's) drive further expansion, so a provider that ignores
    a factor does not pull in unnecessary upstream work. Closed-loop
    composites are planned as a single node. A capability that would
    transitively depend on itself is rejected, so plans are always acyclic.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        bindings: MechanismCapabilityMap = DEFAULT_MECHANISM_CAPABILITIES,
        selector: Selector = cheapest_usable,
    ):
        self.registry = registry
        self.ontology = registry.ontology
        self.bindings = bindings
        self.selector = selector

    def plan(
        self,
        goal: EvaluationGoal,
        context: OperatingContext,
        available: Sequence[DataKind] = (DataKind.DEPLOYMENT,),
    ) -> ExecutionPlan:
        preferred: tuple[str, ...] = ()
        if goal.mechanism_id:
            preferred = self.bindings.binding(goal.mechanism_id).required
        # Nodes are inserted after their inputs resolve, so insertion order is
        # already topological.
        nodes: dict[str, PlanNode] = {}
        producers: dict[DataKind, str] = {kind: INITIAL for kind in available}
        measure_sources: dict[str, str] = {}
        gaps: list[PlanGap] = []

        def ranked(candidates: Sequence[Capability]) -> list[Capability]:
            return sorted(
                candidates,
                key=lambda capability: (
                    capability.id not in preferred,
                    preferred.index(capability.id) if capability.id in preferred else 0,
                    capability.id,
                ),
            )

        def ensure(capability: Capability, stack: tuple[str, ...]) -> str:
            if capability.id in nodes:
                return capability.id
            if capability.id in stack:
                raise _Unsatisfiable(
                    PlanGap(
                        kind=GapKind.UNPRODUCIBLE_INPUT,
                        subject=capability.id,
                        reason="capability would depend on itself",
                    )
                )
            options = self.registry.options(capability.id, context)
            chosen = self.selector(capability, options)
            if chosen is None:
                raise _Unsatisfiable(
                    PlanGap(
                        kind=GapKind.NO_PROVIDER,
                        subject=capability.id,
                        reason=_no_provider_reason(options),
                    )
                )
            provision = self.registry.get(chosen.manifest_key).provision(capability.id)
            edges = tuple(
                Edge(
                    port=port.name,
                    kind=port.kind,
                    source=produce(port.kind, (*stack, capability.id)),
                )
                for port in provision.inputs
            )
            nodes[capability.id] = PlanNode(
                id=capability.id,
                capability_id=capability.id,
                provider_key=chosen.manifest_key,
                inputs=edges,
                produces=tuple(port.kind for port in provision.outputs),
                measures=provision.measures,
                alternatives=tuple(
                    option.manifest_key
                    for option in options
                    if option.usable and option.manifest_key != chosen.manifest_key
                ),
            )
            for kind in nodes[capability.id].produces:
                if kind != DataKind.MEASURE:
                    producers.setdefault(kind, capability.id)
            return capability.id

        def attempt(capability: Capability, stack: tuple[str, ...]) -> str:
            saved = (dict(nodes), dict(producers))
            try:
                return ensure(capability, stack)
            except _Unsatisfiable:
                for state, snapshot in zip((nodes, producers), saved):
                    state.clear()
                    state.update(snapshot)
                raise

        def produce(kind: DataKind, stack: tuple[str, ...]) -> str:
            if kind in producers:
                return producers[kind]
            failures: list[PlanGap] = []
            for capability in ranked(self.ontology.producers(kind)):
                try:
                    return attempt(capability, stack)
                except _Unsatisfiable as error:
                    failures.append(error.gap)
            raise _Unsatisfiable(
                PlanGap(
                    kind=GapKind.UNPRODUCIBLE_INPUT,
                    subject=kind.value,
                    reason="; ".join(f"{gap.subject}: {gap.reason}" for gap in failures)
                    or "no capability produces this kind",
                )
            )

        for measure in goal.measures:
            candidates = ranked(self.ontology.measuring(measure))
            if not candidates:
                gaps.append(
                    PlanGap(
                        kind=GapKind.UNMEASURABLE,
                        subject=measure,
                        reason="no ontology capability declares this measure",
                    )
                )
                continue
            failures = []
            for capability in candidates:
                try:
                    node_id = attempt(capability, ())
                except _Unsatisfiable as error:
                    failures.append(error.gap)
                    continue
                if measure in nodes[node_id].measures:
                    measure_sources[measure] = node_id
                    break
                failures.append(
                    PlanGap(
                        kind=GapKind.NO_PROVIDER,
                        subject=capability.id,
                        reason=f"bound provider does not emit {measure}",
                    )
                )
            else:
                gaps.extend(failures)
                gaps.append(
                    PlanGap(
                        kind=GapKind.NO_PROVIDER,
                        subject=measure,
                        reason="no usable provider can produce this measure",
                    )
                )

        return ExecutionPlan(
            goal=goal,
            context=context,
            nodes=tuple(nodes.values()),
            measure_sources=measure_sources,
            gaps=tuple(dict.fromkeys(gaps)),
        )


def _no_provider_reason(options: tuple[ProviderOption, ...]) -> str:
    if not options:
        return "no registered provider"
    details = []
    for option in options:
        reasons = [*option.offered.violated]
        if option.validity.violated:
            reasons.append(f"outside validity: {', '.join(option.validity.violated)}")
        if option.offered.unknown:
            reasons.append(f"unknown conditions: {', '.join(option.offered.unknown)}")
        details.append(f"{option.manifest_key} ({'; '.join(reasons) or 'rejected'})")
    return "no usable provider: " + ", ".join(details)


class NodeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeRecord(StrictModel):
    """Reproducible record of one provider invocation."""

    node_id: str
    capability_id: str
    provider_key: str
    status: NodeStatus
    input_digests: dict[str, str] = Field(default_factory=dict)
    output_digests: dict[str, str] = Field(default_factory=dict)
    upstream: tuple[str, ...] = ()
    error: str | None = None


class UncertaintySource(StrictModel):
    """One contributor to a measure's uncertainty.

    The producing node contributes the measure's own error. Each upstream
    node contributes through the payloads it produced; it is ``declared`` when
    its provider is exact (rule-based) or publishes an error model.
    """

    node_id: str
    provider_key: str
    measure: str | None = None
    error: MeasureError | None = None
    declared: bool


class EvidenceMeasure(StrictModel):
    """A measure with its provider, lineage, and uncertainty sources."""

    name: str
    value: float | bool
    unit: str | None
    error: MeasureError | None
    node_id: str
    provider_key: str
    lineage: tuple[str, ...]
    uncertainty_sources: tuple[UncertaintySource, ...]

    @property
    def fully_quantified(self) -> bool:
        return all(source.declared for source in self.uncertainty_sources)


class ExecutionRecord(StrictModel):
    plan: ExecutionPlan
    nodes: tuple[NodeRecord, ...]
    evidence: tuple[EvidenceMeasure, ...]

    @property
    def succeeded(self) -> bool:
        return self.plan.complete and all(
            node.status == NodeStatus.SUCCEEDED for node in self.nodes
        )

    def measure(self, name: str) -> EvidenceMeasure:
        return next(item for item in self.evidence if item.name == name)


def digest(value: BaseModel) -> str:
    return "sha256:" + hashlib.sha256(value.model_dump_json().encode()).hexdigest()


def execute(
    plan: ExecutionPlan,
    tools: Mapping[str, ToolAdapter],
    initial: Mapping[DataKind, BaseModel],
) -> ExecutionRecord:
    """Run plan nodes in order and derive evidence for the goal's measures."""

    outputs: dict[str, dict[DataKind, BaseModel]] = {INITIAL: dict(initial)}
    records: dict[str, NodeRecord] = {}
    lineage: dict[str, tuple[str, ...]] = {INITIAL: ()}
    for node in plan.nodes:
        sources = tuple(dict.fromkeys(edge.source for edge in node.inputs))
        lineage[node.id] = tuple(
            dict.fromkeys(
                ancestor
                for source in sources
                if source != INITIAL
                for ancestor in (*lineage[source], source)
            )
        )
        blocked = [
            source
            for source in sources
            if source != INITIAL and records[source].status != NodeStatus.SUCCEEDED
        ]
        base = {
            "node_id": node.id,
            "capability_id": node.capability_id,
            "provider_key": node.provider_key,
            "upstream": lineage[node.id],
        }
        if blocked:
            records[node.id] = NodeRecord(
                **base,
                status=NodeStatus.SKIPPED,
                error=f"upstream did not succeed: {', '.join(blocked)}",
            )
            continue
        inputs = {edge.port: outputs[edge.source][edge.kind] for edge in node.inputs}
        tool = tools.get(node.provider_key)
        try:
            if tool is None:
                raise LookupError(f"no adapter bound for {node.provider_key}")
            produced = tool.invoke(node.capability_id, inputs)
        except Exception as error:  # noqa: BLE001 - recorded, not swallowed
            records[node.id] = NodeRecord(
                **base,
                status=NodeStatus.FAILED,
                input_digests={name: digest(value) for name, value in inputs.items()},
                error=f"{type(error).__name__}: {error}",
            )
            continue
        provision = tool.contract.provision(node.capability_id)
        outputs[node.id] = {
            port.kind: produced[port.name] for port in provision.outputs
        }
        records[node.id] = NodeRecord(
            **base,
            status=NodeStatus.SUCCEEDED,
            input_digests={name: digest(value) for name, value in inputs.items()},
            output_digests={name: digest(value) for name, value in produced.items()},
        )

    evidence = []
    for name, node_id in plan.measure_sources.items():
        if records[node_id].status != NodeStatus.SUCCEEDED:
            continue
        measures = outputs[node_id].get(DataKind.MEASURE)
        if not isinstance(measures, MeasureSet):
            continue
        try:
            measure = measures.get(name)
        except KeyError:
            continue
        tool = tools[plan.node(node_id).provider_key]
        own = measure.error or _declared_error(tool, name, measure.value)
        evidence.append(
            EvidenceMeasure(
                name=name,
                value=measure.value,
                unit=measure.unit,
                error=own,
                node_id=node_id,
                provider_key=plan.node(node_id).provider_key,
                lineage=lineage[node_id],
                uncertainty_sources=_uncertainty_sources(
                    plan, tools, lineage[node_id], node_id, name, own
                ),
            )
        )
    return ExecutionRecord(
        plan=plan,
        nodes=tuple(records[node.id] for node in plan.nodes),
        evidence=tuple(evidence),
    )


def _declared_error(
    tool: ToolAdapter, measure: str, value: float | bool
) -> MeasureError | None:
    spec = tool.contract.error_for(measure)
    if spec is None or spec.value is None or isinstance(value, bool):
        return None
    match spec.kind:
        case UncertaintyKind.ABSOLUTE_BOUND:
            return MeasureError(kind="absolute_bound", value=spec.value)
        case UncertaintyKind.RELATIVE_BOUND:
            return MeasureError(kind="absolute_bound", value=abs(value) * spec.value)
        case UncertaintyKind.STANDARD_DEVIATION:
            return MeasureError(kind="standard_deviation", value=spec.value)
    return None


def _uncertainty_sources(
    plan: ExecutionPlan,
    tools: Mapping[str, ToolAdapter],
    lineage: Sequence[str],
    node_id: str,
    measure: str,
    error: MeasureError | None,
) -> tuple[UncertaintySource, ...]:
    """Make every contributor explicit instead of hiding unquantified ones.

    Numerical propagation of these errors belongs to the
    ``uncertainty.propagation`` capability; this record tells a judge whether
    every contributor to a measure is quantified.
    """

    sources = []
    for upstream in lineage:
        node = plan.node(upstream)
        contract = tools[node.provider_key].contract
        sources.append(
            UncertaintySource(
                node_id=upstream,
                provider_key=node.provider_key,
                declared=contract.fidelity == FidelityClass.RULE or bool(contract.errors),
            )
        )
    sources.append(
        UncertaintySource(
            node_id=node_id,
            provider_key=plan.node(node_id).provider_key,
            measure=measure,
            error=error,
            declared=error is not None
            or tools[plan.node(node_id).provider_key].contract.fidelity
            == FidelityClass.RULE,
        )
    )
    return tuple(sources)
