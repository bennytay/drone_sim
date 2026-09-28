# Capability graph planning and execution v0.1

The graph layer turns an evaluation goal into an executed, provenance-carrying
test path from Deployment IR to deterministic evidence.

## Responsibility split

An agent decides *what* to evaluate: which hypotheses to pursue and which
measures would confirm or falsify them. `EvaluationGoal.for_hypothesis` derives
the goal from a `FailureHypothesis`'s confirm and falsify observables and its
taxonomy mechanism. Everything after that is deterministic graph search: the
same goal, context, and registry always yield the same plan.

## Planning

`GraphPlanner.plan(goal, context)` chains backwards:

1. each goal measure resolves to capabilities that declare it, preferring the
   mechanism's capability binding in its declared order;
2. each capability binds to one provider through a selector — by default the
   registry's first usable option (offered here, not outside validity, then
   cheapest fidelity, cost, and runtime);
3. the **provider's** input ports, not the capability's, drive further
   expansion, so an energy model that ignores atmosphere does not pull in
   atmosphere estimation;
4. each input kind is produced by an existing node, an initial value, or a
   newly planned producer, with failed alternatives rolled back.

The resulting `ExecutionPlan` is topologically ordered and validated: every edge
names a port, a data kind, and a planned source. Each node records the
alternative usable providers it did not choose.

## Alternatives, cycles, and closed loops

Alternatives are compared by the registry ordering; fidelity routing replaces
the default selector to justify or escalate choices. Closed-loop composites
such as `autonomy.closed_loop_flight` are planned as one node supplied by one
provider, never expanded into their feedback-coupled components. A capability
that would transitively require itself is rejected, so plans are always
acyclic.

## Unsatisfied capabilities

Goals the registry cannot meet are returned as explicit `PlanGap`s rather than
dropped: `unmeasurable` (no capability declares the measure), `no_provider`
(no usable provider, with each rejected provider and its reasons such as
airframe conditions or validity violations), and `unproducible_input`. A plan
with gaps is not `complete`.

## Execution, provenance, and uncertainty

`execute(plan, tools, initial)` invokes each node through its `ToolAdapter`
and records a `NodeRecord` with status, provider key and version, upstream
lineage, and SHA-256 digests of canonical inputs and outputs. A failed provider
is recorded with its error, and every dependent node is skipped rather than run
on missing data. Execution is deterministic and reproducible from the plan and
initial values.

Each goal measure becomes an `EvidenceMeasure` with value, unit, producing
provider, lineage, and error. Errors come from the measure itself or from the
provider's declared error specification. `uncertainty_sources` names every
contributing node and whether it is exact (rule-based) or publishes an error
model; `fully_quantified` is false whenever any contributor is unquantified.
Numerical propagation across contributors is the job of the
`uncertainty.propagation` capability, not hidden arithmetic in the runtime.
