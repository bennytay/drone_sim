# Model and tool registry v0.1

The registry is how analytical models, empirical fits, geometry engines,
physics models, simulators, customer models, and external services tell the
planner what they can do. A provider registers once with a `ToolManifest`; the
planner then queries capabilities and compares providers without bespoke
integration or knowledge of provider internals.

## Manifest contract

Each manifest (`manifest_version` `0.1.0`) is keyed by `id@version` and declares:

| Concern | Field |
| --- | --- |
| provided capabilities | `provides[].capability_id` |
| required canonical inputs and outputs | `provides[].inputs`, `provides[].outputs` |
| measures actually emitted | `provides[].measures` |
| supported drone airframes and deployments | `airframes`, region `deployment_tags` |
| claimed validity region | `validity_region` |
| fidelity class | `fidelity` |
| uncertainty and error | `errors[]` per measure, with basis |
| empirical validation coverage | `trust_regions[]` |
| runtime and compute | `runtime` |
| cost class | `cost` |
| location and runtime mode | `execution_mode` |
| disclosure level | `disclosure` |
| version and reproducibility | `version`, `reproducibility` |

Provisions default to the capability's canonical ports and measures. A provider
may accept fewer canonical inputs (for example an energy model that ignores
atmosphere) or emit fewer measures, but it may not require non-canonical
inputs, change canonical outputs, or claim measures the ontology does not
define. Registration fails rather than silently adapting a mismatched contract.

Fidelity classes are ordered `rule`, `analytical`, `empirical`, `geometric`,
`physics`, and `high_fidelity_simulation`. Cost classes are ordered
`negligible`, `low`, `medium`, and `high`.

## Conditional capabilities

A provision may declare `conditions`: a region of airframes, deployment tags,
and variable bounds within which the capability is offered at all. A hover
power model can offer `energy.route_demand` only for multirotors while offering
`energy.reserve_assessment` for every supported airframe. Conditions answer
“can this tool do it here?”; the validity region answers “is its claim
credible here?”.

## Validity and trust regions

`validity_region` is the provider's claimed domain of applicability.
`trust_regions` record where validation evidence exists, with an evidence
reference and sample count. They are deliberately separate: an empirical fit
may claim validity to 14 m/s wind while its fleet data only supports 9 m/s.
Empirical providers must declare at least one trust region.

Region checks are three-valued. A context variable a region bounds but the
deployment does not supply yields `unknown`, never `inside`.

## Private and customer models

`disclosure: opaque` lets customer or third-party models register without
exposing internals. Opaque providers must run behind a service boundary
(`remote_service` or `customer_hosted`) and must declare per-measure errors
and validation trust regions, so the planner can still judge credibility from
the contract rather than the implementation.

## Reproducibility

Every manifest declares whether it is deterministic. Stochastic providers must
accept a controlled seed. Optional artifact digests and environment references
pin the exact model or container used.

## Comparing providers

`ToolRegistry.options(capability_id, context)` returns every provider of a
capability evaluated against an `OperatingContext`, with offered-condition,
validity, and trust results. Ordering is deterministic: usable providers first,
then lower fidelity, lower cost, shorter runtime, and manifest key. This is the
input to fidelity routing, which decides when the cheapest usable provider is
credible enough and when to escalate.

Example manifests for an analytical energy model, an empirical wind-margin
regression, a geometry engine, a high-fidelity closed-loop simulator, and an
opaque customer battery model live in `examples/tool_manifests`.
