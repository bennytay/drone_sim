"""Registration contract for models and tools that provide capabilities.

A manifest describes what a provider can compute, where it is valid, how
faithful and uncertain it is, what it costs to run, and how to reproduce it.
The planner compares manifests; it never inspects provider internals.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from drone_sim.capabilities import (
    DEFAULT_CAPABILITY_ONTOLOGY,
    CapabilityOntology,
    Port,
)
from drone_sim.ir import StrictModel

Airframe = Literal["multirotor", "fixed_wing", "vtol"]


class FidelityClass(StrEnum):
    """Ordered from cheapest abstraction to richest simulation."""

    RULE = "rule"
    ANALYTICAL = "analytical"
    EMPIRICAL = "empirical"
    GEOMETRIC = "geometric"
    PHYSICS = "physics"
    HIGH_FIDELITY_SIMULATION = "high_fidelity_simulation"

    @property
    def rank(self) -> int:
        return list(FidelityClass).index(self)


class CostClass(StrEnum):
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return list(CostClass).index(self)


class ExecutionMode(StrEnum):
    IN_PROCESS = "in_process"
    LOCAL_PROCESS = "local_process"
    REMOTE_SERVICE = "remote_service"
    CUSTOMER_HOSTED = "customer_hosted"


class Disclosure(StrEnum):
    """How much of a provider's internals the platform may inspect."""

    OPEN = "open"
    DOCUMENTED = "documented"
    OPAQUE = "opaque"


class Interval(StrictModel):
    """A closed range for one canonical operating variable in SI units."""

    variable: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    minimum: float | None = None
    maximum: float | None = None
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("interval requires a minimum or maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("interval minimum cannot exceed maximum")
        return self

    def contains(self, value: float) -> bool:
        return (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )


class OperatingContext(StrictModel):
    """Deployment conditions at which a provider would be evaluated."""

    airframe: Airframe
    deployment_tags: tuple[str, ...] = ()
    variables: dict[str, float] = Field(default_factory=dict)


class RegionStatus(StrEnum):
    INSIDE = "inside"
    OUTSIDE = "outside"
    UNKNOWN = "unknown"


class RegionCheck(StrictModel):
    status: RegionStatus
    violated: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


class Region(StrictModel):
    """Bounds, airframes, and deployment tags that delimit a domain.

    Empty ``airframes`` or ``deployment_tags`` impose no restriction. A
    variable absent from the context yields ``unknown`` rather than inside.
    """

    bounds: tuple[Interval, ...] = ()
    airframes: tuple[Airframe, ...] = ()
    deployment_tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_variables(self) -> Self:
        variables = [bound.variable for bound in self.bounds]
        if len(variables) != len(set(variables)):
            raise ValueError("region bounds must name each variable once")
        return self

    def check(self, context: OperatingContext) -> RegionCheck:
        violated: list[str] = []
        unknown: list[str] = []
        if self.airframes and context.airframe not in self.airframes:
            violated.append("airframe")
        if self.deployment_tags and not set(self.deployment_tags) & set(
            context.deployment_tags
        ):
            violated.append("deployment_tags")
        for bound in self.bounds:
            value = context.variables.get(bound.variable)
            if value is None:
                unknown.append(bound.variable)
            elif not bound.contains(value):
                violated.append(bound.variable)
        if violated:
            status = RegionStatus.OUTSIDE
        elif unknown:
            status = RegionStatus.UNKNOWN
        else:
            status = RegionStatus.INSIDE
        return RegionCheck(
            status=status, violated=tuple(violated), unknown=tuple(unknown)
        )


class CapabilityProvision(StrictModel):
    """One capability a provider offers, optionally only under conditions.

    Inputs may be a subset of the capability's canonical inputs when a
    provider ignores a factor; it must still emit every canonical output.
    ``conditions`` declare when the capability is offered at all, for example
    a hover model that only provides dynamics for multirotors.
    """

    capability_id: str = Field(min_length=1)
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    measures: tuple[str, ...] = ()
    conditions: Region | None = None


class UncertaintyKind(StrEnum):
    NONE = "none"
    ABSOLUTE_BOUND = "absolute_bound"
    RELATIVE_BOUND = "relative_bound"
    STANDARD_DEVIATION = "standard_deviation"
    DISTRIBUTION = "distribution"


class ErrorSpec(StrictModel):
    """Declared error for one measure, with the basis for that declaration."""

    measure: str = Field(min_length=1)
    kind: UncertaintyKind
    value: float | None = Field(default=None, ge=0)
    unit: str | None = None
    basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def value_matches_kind(self) -> Self:
        needs_value = self.kind not in {UncertaintyKind.NONE, UncertaintyKind.DISTRIBUTION}
        if needs_value and self.value is None:
            raise ValueError(f"{self.kind.value} error requires a value")
        return self


class TrustRegion(StrictModel):
    """Region where empirical validation evidence supports the provider."""

    region: Region
    evidence_ref: str = Field(min_length=1)
    sample_count: int = Field(ge=1)


class RuntimeSpec(StrictModel):
    typical_runtime_s: float = Field(gt=0)
    compute: Literal["cpu", "gpu"] = "cpu"
    min_memory_gb: float | None = Field(default=None, gt=0)
    parallel_instances: int = Field(default=1, ge=1)


class Reproducibility(StrictModel):
    deterministic: bool
    seed_controlled: bool = False
    artifact_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    environment: str | None = None

    @model_validator(mode="after")
    def replayable(self) -> Self:
        if not (self.deterministic or self.seed_controlled):
            raise ValueError("stochastic providers must accept a controlled seed")
        return self


class ToolManifest(StrictModel):
    """Everything the planner may know about a model or tool."""

    manifest_version: Literal["0.1.0"] = "0.1.0"
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str | None = None
    provides: tuple[CapabilityProvision, ...] = Field(min_length=1)
    airframes: tuple[Airframe, ...] = Field(min_length=1)
    validity_region: Region = Region()
    fidelity: FidelityClass
    errors: tuple[ErrorSpec, ...] = ()
    trust_regions: tuple[TrustRegion, ...] = ()
    runtime: RuntimeSpec
    cost: CostClass
    execution_mode: ExecutionMode
    disclosure: Disclosure = Disclosure.OPEN
    reproducibility: Reproducibility

    @model_validator(mode="after")
    def coherent(self) -> Self:
        capabilities = [provision.capability_id for provision in self.provides]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("a manifest may provide each capability once")
        if self.disclosure == Disclosure.OPAQUE:
            if self.execution_mode not in {
                ExecutionMode.REMOTE_SERVICE,
                ExecutionMode.CUSTOMER_HOSTED,
            }:
                raise ValueError("opaque providers must run as a service boundary")
            if not (self.errors and self.trust_regions):
                raise ValueError(
                    "opaque providers must declare errors and validation trust regions"
                )
        if self.fidelity == FidelityClass.EMPIRICAL and not self.trust_regions:
            raise ValueError("empirical providers must declare trust regions")
        return self

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    def provision(self, capability_id: str) -> CapabilityProvision:
        for provision in self.provides:
            if provision.capability_id == capability_id:
                return provision
        raise KeyError(capability_id)

    def error_for(self, measure: str) -> ErrorSpec | None:
        return next((error for error in self.errors if error.measure == measure), None)


class ProviderOption(StrictModel):
    """One registered provider evaluated for a capability and context."""

    manifest_key: str
    capability_id: str
    fidelity: FidelityClass
    cost: CostClass
    typical_runtime_s: float
    offered: RegionCheck
    validity: RegionCheck
    trusted: bool
    measures: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return (
            self.offered.status == RegionStatus.INSIDE
            and self.validity.status != RegionStatus.OUTSIDE
        )


class RegistrationError(ValueError):
    pass


class ToolRegistry:
    """Validated set of manifests that the planner can query and compare."""

    def __init__(self, ontology: CapabilityOntology = DEFAULT_CAPABILITY_ONTOLOGY):
        self.ontology = ontology
        self._manifests: dict[str, ToolManifest] = {}

    def register(self, manifest: ToolManifest) -> ToolManifest:
        if manifest.key in self._manifests:
            raise RegistrationError(f"{manifest.key} is already registered")
        provides = []
        for provision in manifest.provides:
            provides.append(self._resolve(manifest, provision))
        manifest = manifest.model_copy(update={"provides": tuple(provides)})
        measured = {m for provision in provides for m in provision.measures}
        for error in manifest.errors:
            if error.measure not in measured:
                raise RegistrationError(
                    f"{manifest.key} declares error for unprovided measure "
                    f"{error.measure}"
                )
        self._manifests[manifest.key] = manifest
        return manifest

    def load_directory(self, directory: Path) -> tuple[ToolManifest, ...]:
        return tuple(
            self.register(ToolManifest.model_validate(json.loads(path.read_text())))
            for path in sorted(directory.glob("*.json"))
        )

    def _resolve(
        self, manifest: ToolManifest, provision: CapabilityProvision
    ) -> CapabilityProvision:
        try:
            capability = self.ontology.get(provision.capability_id)
        except KeyError:
            raise RegistrationError(
                f"{manifest.key} provides unknown capability {provision.capability_id}"
            ) from None
        inputs = provision.inputs or capability.inputs
        outputs = provision.outputs or capability.outputs
        measures = provision.measures or capability.measures
        extra_inputs = set(inputs) - set(capability.inputs)
        if extra_inputs:
            raise RegistrationError(
                f"{manifest.key} requires non-canonical inputs for {capability.id}: "
                f"{', '.join(sorted(port.name for port in extra_inputs))}"
            )
        missing_outputs = set(capability.outputs) - set(outputs)
        if missing_outputs or set(outputs) - set(capability.outputs):
            raise RegistrationError(
                f"{manifest.key} outputs for {capability.id} must match the capability"
            )
        unknown_measures = set(measures) - set(capability.measures)
        if unknown_measures:
            raise RegistrationError(
                f"{manifest.key} emits undeclared measures for {capability.id}: "
                f"{', '.join(sorted(unknown_measures))}"
            )
        return provision.model_copy(
            update={"inputs": inputs, "outputs": outputs, "measures": measures}
        )

    @property
    def manifests(self) -> tuple[ToolManifest, ...]:
        return tuple(self._manifests.values())

    def get(self, key: str) -> ToolManifest:
        return self._manifests[key]

    def options(
        self, capability_id: str, context: OperatingContext
    ) -> tuple[ProviderOption, ...]:
        """Providers for a capability, usable first, then cheapest fidelity.

        Ordering is deterministic: usability, fidelity rank, cost rank,
        typical runtime, then manifest key.
        """

        options: list[ProviderOption] = []
        for manifest in self._manifests.values():
            provision = next(
                (p for p in manifest.provides if p.capability_id == capability_id),
                None,
            )
            if provision is None:
                continue
            offered = (provision.conditions or Region()).check(context)
            if context.airframe not in manifest.airframes:
                offered = RegionCheck(
                    status=RegionStatus.OUTSIDE,
                    violated=("airframe", *offered.violated),
                    unknown=offered.unknown,
                )
            options.append(
                ProviderOption(
                    manifest_key=manifest.key,
                    capability_id=capability_id,
                    fidelity=manifest.fidelity,
                    cost=manifest.cost,
                    typical_runtime_s=manifest.runtime.typical_runtime_s,
                    offered=offered,
                    validity=manifest.validity_region.check(context),
                    trusted=any(
                        trust.region.check(context).status == RegionStatus.INSIDE
                        for trust in manifest.trust_regions
                    ),
                    measures=provision.measures,
                )
            )
        return tuple(
            sorted(
                options,
                key=lambda option: (
                    not option.usable,
                    option.fidelity.rank,
                    option.cost.rank,
                    option.typical_runtime_s,
                    option.manifest_key,
                ),
            )
        )
