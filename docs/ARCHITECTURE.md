# Architecture

This document has two deliberately separate parts:

1. **[Intended architecture](#intended-architecture)** — the target system.
   Written in the present tense as a design, *not* a claim that it exists.
2. **[Current implementation](#current-implementation)** — what the code does
   today, with a status on every stage.

Per-component detail, limitations, and known defects live in
[`CURRENT_STATE.md`](CURRENT_STATE.md). Product intent lives in `PRODUCT.md`;
the reasons behind settled choices live in `DECISIONS.md`.

Legend: ✅ implemented · 🟡 partial · ⚪ not implemented · 🔴 known defect.

## Intended architecture

> Everything in this section is the **target design**. Each stage heading
> carries its current status; do not read an unmarked sentence here as proof
> that behavior exists. Check [Current implementation](#current-implementation).

### System flow

```text
local-folder context agent
  -> evidence-backed Deployment IR
  -> failure hypothesis engine
  -> capability/model registry
  -> Scenario Spec
  -> analytical / geometry / physics / Isaac backends
  -> deterministic judges
  -> adaptive boundary search
  -> readiness report
  -> optional post-deployment learning loop
```

Each arrow is a typed boundary. Agent decisions can choose what to investigate,
but canonical state, execution inputs, outputs, and verdicts remain inspectable
and reproducible outside an LLM context window.

### Stages


#### Local-folder context agent — current status: ✅

The context layer receives operator-controlled deployment sources read-only. It
indexes before reading, searches according to unresolved dependencies, and
invokes deterministic adapters for documents, routes, logs, GIS, meshes, and
structured files. Candidate facts, inspected sources, missing data, conflicts,
and provenance persist outside the model context so investigation is resumable
and auditable.

The agent decides what evidence to seek and which adapter to invoke. It does not
invent source facts or hide parsing inside free-form reasoning.

Source parsing is a deterministic registry boundary. Each adapter declares its
supported suffixes and returns a common bounded `ParsedSource` containing the
artifact kind, structured summary, source hash, byte size, materialized size,
and truncation state. Structured manifests remain size-limited; large CSV logs
are streamed into samples and numeric ranges; documents expose bounded text;
and drone logs, site geometry, point clouds, images, and video expose metadata
without loading raw binary or time-series content into agent context.

Reconstruction is dependency-driven rather than folder-layout-driven. Reusable
drone dependency templates define aliases, search terms, preferred artifact
formats, requiredness, and a last-resort clarification question. Metadata search
combines lexical relevance, optional semantic ranking, format preference, and
explicit current/stale filename signals. Parsed summaries are cached outside
the model context and invalidated when the folder index changes. Deterministic
alias normalization handles renamed and nested operator bundles while retaining
exact original source pointers. Shared deployment, vehicle, and site identifiers
link evidence across structured files and bounded document summaries.

The agent asks the operator only after relevant files and structured fallbacks
have been exhausted. Clarification requests name the unresolved material field,
the evidence paths already searched, and the concrete question needed to cross
the readiness threshold.

#### Deployment IR — current status: ✅

Deployment IR is the canonical description of deployment reality and intent:
vehicle, payload, mission, route, environment, conditions, autonomy,
constraints, success criteria, telemetry references, and attached model
references. It is typed, versioned, and independent of DJI, PX4, Isaac, or any
other vendor or backend.

Source adapters translate source-specific semantics into Deployment IR. They do
not leak their native field names into the canonical representation.

Deployment IR travels in a versioned evidence envelope. Every populated scalar
field has a stable JSON Pointer and a selected evidence candidate recording its
exact source anchor, extraction method, qualitative uncertainty, and value
origin. Competing candidates remain attached rather than being discarded.
Explicit assumptions are identified and justified. Inferred, estimated, and
model-derived candidates cite their inputs by stable candidate ID, allowing
scenario generation and reporting to retain the complete lineage. Envelope
validation rejects missing coverage, mismatched selected values, dangling
references, and derivation cycles.

A deterministic completeness validator evaluates that envelope against a typed
drone evaluation profile. It reports resolved and missing dependencies,
out-of-range or non-canonical values, insufficient confidence, and competing
candidates. Its terminal state is one of `ready`, `incomplete`, `uncertain`,
`conflicting`, or `invalid`. A contradiction remains blocking until a
resolution record accounts for the selected and rejected candidates. This
gives the context agent a repeatable “what is unresolved?” query and prevents
hypothesis generation or testing before its declared context threshold is met.

#### Failure hypothesis engine — current status: 🟡 taxonomy, coverage, contract · ⚪ generator

The hypothesis engine maps grounded deployment context to plausible failure
mechanisms. LLMs may propose, refine, and prioritize hypotheses, but each
hypothesis must state its applicability, required evidence, causal mechanism,
and testable outcome. Coverage and stopping rules remain explicit.

The hypothesis contract preserves concise causal reasoning as a sequence and
requires deployment-evidence support, an uncertainty basis, candidate test
modalities, and both confirming and falsifying observations. It never lets an
agent assert a quantitative pass/fail threshold; registered deterministic
judges bind observations to versioned criteria.

Versioned prompts reach hosted models only through the provider-neutral LLM
edge. It records the selected task model and provider request identity, accepts
typed deterministic tools, validates output directly into an existing Pydantic
contract, asks for a bounded repair using validation errors, and then fails
closed. A missing API key leaves the deterministic path available. Customer
data controls are a separate safety stage.

Operator files are untrusted evidence, never instructions. Before a hosted
call, deployment policy must allow it; configured patterns are redacted and
the remaining text is explicitly delimited. The ledger records the hash of the
exact delimited payload. LLM output is only a typed proposal: conflict
resolution, thresholds, and deterministic judgments remain unavailable as LLM
contracts; inferred evidence must retain an anchor whose hash matches checked
source bytes.

Every edge invocation also receives a persistent ledger entry: prompt and
request hashes, model, explicit candidate/file-hash references, linked context
trace indices, response, usage, latency, cost, validation outcome, and live or
replay mode. Replay keys responses by request hash and never falls through to
the network. Per-stage call, token, and cost budgets stop the agent with an
explicit reason. Retention and request-data controls remain separate safety
work.

A versioned drone-only failure taxonomy supplies the systematic discovery
surface. Its stable hierarchy separates broad domains, mechanism branches, and
testable leaves. Leaves identify causal variables, observable outcomes, and the
Deployment IR context needed to assess them; they do not assert applicability
or quantitative verdicts. Upstream aircraft and autonomy development defects
remain outside the catalog unless deployment evidence identifies a concrete
site- or mission-specific trigger.

Applicability and coverage are a deterministic layer over that taxonomy. A
mechanism is `applies`, `ruled_out`, or `unknown` based on recorded Deployment
IR predicates; absent evidence remains unknown rather than becoming irrelevant.
Applicable mechanisms begin unexamined and move to tested, uncertain, or
escalated only through investigation results. The coverage map also records
residual unknown risks, so catalog coverage is never misrepresented as a safety
proof.

#### Capability and model registry — current status: ✅

The registry describes available parsers, analytical models, geometry checks,
learned models, physics tools, simulators, and judges through typed inputs,
outputs, cost, fidelity, validity region, and evidence requirements. Canonical
capabilities are separate from vendor implementations so a backend can be
replaced without changing test intent.

A versioned capability ontology names what can be computed — for example wind
field estimation, route energy demand, trajectory clearance, or closed-loop
flight — through typed canonical data kinds and named measures, without
fidelity, cost, or vendor information. Every failure-taxonomy mechanism is
bound to a minimum capability set whose inputs are satisfiable from Deployment
IR and whose measures cover the mechanism's observable outcomes. Closed-loop
composites are provided as a unit so planning graphs remain acyclic.

Providers register a versioned `ToolManifest` declaring the capabilities they
provide (optionally under conditions), canonical ports, emitted measures,
supported airframes, validity region, fidelity class, per-measure errors,
empirical trust regions, runtime, cost, execution mode, disclosure, and
reproducibility. Registration validates every provision against the ontology.
Opaque customer models expose only this contract and validation evidence. The
registry returns a deterministic comparison of providers for a capability in a
given operating context, keeping claimed validity separate from validated trust.

Providers exchange canonical payloads: one Pydantic type per data kind, SI
units, a shared local East-North-Up frame, UTC-epoch-relative time, and pinned
references for large series and assets. Tool adapters validate every port,
frame, and emitted measure at the boundary. Converting Deployment IR into
canonical payloads is a registered provider like any other; native model or
simulator formats stay inside each adapter.

A deterministic graph planner expands an evaluation goal — typically a
hypothesis's confirm and falsify observables — backwards into capabilities,
binds one provider per capability, and lets the chosen provider's input ports
drive further expansion. Plans are acyclic, closed-loop composites are single
nodes, and unsatisfiable measures, providers, or inputs are returned as explicit
gaps. Execution records input and output digests, lineage, failures, skipped
dependents, and per-measure uncertainty sources.

#### Scenario Spec — current status: ⚪

Scenario Spec is the simulator- and model-agnostic contract for a test. It
captures initial state, relevant environment, variations, interventions,
observations, and success measures. Backend adapters compile this contract into
tool-specific execution rather than embedding Isaac or another simulator's API
in the canonical spec.

An LLM must not generate arbitrary simulator code in the core path. It chooses
from typed, validated capabilities and parameters.

#### Execution backends and fidelity routing — current status: 🟡 analytical + routing · ⚪ Isaac

The fidelity router starts with the cheapest model credible for the causal
failure mechanism. Examples include static constraints, route geometry,
analytical energy or wind models, specialized physics, and high-fidelity
simulation. It escalates when validity bounds are exceeded, uncertainty is too
large, or a lower-fidelity result lies near a decision boundary.

Isaac Sim and Isaac Lab are the default general high-fidelity backend. A
specialized simulator is justified only when a material drone failure mode
cannot be covered economically and credibly by the existing stack.

Scene realism is causal, not decorative. Introduce geometry, appearance,
dynamics, sensor effects, and environmental detail only when they can affect
the mechanism being tested. Existing meshes, point clouds, CAD, and GIS enter
through the scene-input pipeline; reconstruction from historical imagery or
video comes later.

The versioned routing policy implements this with mechanism floors (closed-loop
composites and appearance-driven perception mechanisms start at high-fidelity
simulation), a selector that prefers the lowest eligible fidelity with
confirmed validity, and boundary assessment of each decision measure against
`boundary_factor` times its declared error. Near-boundary, unquantified, or
unconfirmed-validity results escalate the producing capability one fidelity
class at a time with written justifications. Disagreement between consecutive
levels beyond their combined error is flagged for review rather than resolved
by assuming the higher-fidelity result.

A version-specific trust ledger records validation datasets, residual
distributions, unsupported regions, deployment feedback, and drift for each
model version and customer or deployment scope. It classifies each operating
point as validated, extrapolated, unvalidated, or unsupported and caps finding
confidence accordingly. Routing excludes unsupported providers, prefers better
trust at equal fidelity, escalates untrusted results, and widens optimistic
declared errors with empirical residual bounds.

#### Deterministic judges — current status: ⚪

Backends emit canonical observations and artifacts. Deterministic judges apply
versioned metrics and thresholds to establish results. LLMs may explain a
finding, but they do not establish the underlying pass, fail, margin, or
measurement.

#### Adaptive boundary search — current status: ⚪

The investigation loop varies causally relevant conditions, searches for the
transition between safe and failing behavior, and allocates fidelity where it
changes the decision. Persistent state tracks explored regions, uncertainty,
coverage, and stopping reasons.

#### Readiness report — current status: ⚪

The report summarizes deployment readiness, safe margins, failure boundaries,
unresolved risks, assumptions, and recommended mitigations. Every material
claim links to source evidence, scenario configuration, model version,
execution artifacts, and judge output.

#### Optional post-deployment learning — current status: 🟡 trust ledger only

Observed deployment outcomes can be compared with predictions to measure
residuals and calibrate future audits. Customer-private learning comes first.
Cross-customer learning requires separate governance and must preserve the
validity and provenance of learned updates.

### Responsibility boundary

Agentic components discover context, form hypotheses, plan investigations,
select registered capabilities, decide when to escalate, and summarize results.
Deterministic components parse evidence, validate schemas, execute models and
simulators, compute metrics, judge outcomes, and persist reproducible state.

Provenance and uncertainty cross every stage. A material field or finding must
distinguish observed evidence, deterministic derivation, model output, and
explicit assumption. Conflicts and missing information remain visible rather
than being silently resolved by an LLM.

## Current implementation

This is what runs today. Reproduce it with
`uv run drone-eval agent examples/demo_deployment`
(see [`DEMO.md`](DEMO.md)).

```text
Local deployment folder (read-only)                     ✅  examples/demo_deployment/
  │  DirectoryIndex → ranked search → AdapterRegistry
  ▼
Context search: replay/live LLM or deterministic fallback ✅  context_agent.py, context.py, agent_tools.py
  │  candidates, entity links, trace → state.json
  ▼
Evidence-backed Deployment IR                            ✅  ir.py, provenance.py
  │
  ▼
Context readiness gate (drone_hypothesis_generation_v1)  ✅  validation.py
  │  stops here unless READY (conflicts cannot yet be resolved)
  ▼
Failure taxonomy + applicability map                     🟡  failure_taxonomy.py ✅, coverage.py 🟡 (context-exists rules only)
  │
  ▼
Document extraction (typed replay/live LLM edge)         🟡  document_extraction.py + exact quote validation
  │
  ▼
Failure hypothesis session                               ✅  hypothesis_generator.py + typed replay/live response
  │  optional review via answers file
  ▼
Investigation policy + persisted trace                   🟡  investigation.py, investigation_loop.py, agent_session.py
  │
  ▼
Capability / model selection                             ✅  capabilities.py, registry.py, graph.py (GraphPlanner)
  │
  ▼
Scenario Spec                                            ⚪  not implemented — EvaluationGoal + OperatingContext used directly
  │
  ▼
Models / geometry / Isaac                                🟡  reference_tools.py: rule + analytical energy ✅,
  │                                                          swept-volume clearance 🟡 (no site-geometry provider), Isaac ⚪
  ▼
Execution with lineage + fidelity routing                ✅  graph.py (execute), routing.py (FidelityRouter)
  │  ← stand-in: thresholds bound from IR by golden_path.bind_thresholds
  ▼
Deterministic judges                                     ⚪  not implemented
  │
  ▼
Adaptive scenario / boundary search                      ⚪  not implemented (one nominal condition only)
  │
  ▼
Readiness report                                         ⚪  not implemented — drone-eval prints a labelled demo summary
  │
  ▼
Post-deployment learning                                 🟡  trust.py ledger API; no outcome ingestion
```

### Where the Golden Path stops

- **Real, end to end:** folder to evidence-backed IR, readiness gate,
  applicability map, capability planning, in-process execution, and fidelity
  routing, for the energy-reserve and takeoff-mass mechanisms.
- **Stand-in, clearly labelled in output:** decision thresholds
  (`golden_path.bind_thresholds`) until deterministic judges exist. Recorded
  responses are test fixtures for the real typed LLM boundary, not alternate
  hypothesis semantics.
- **Stops with explicit gaps:** static-obstacle clearance. The planner reports
  that no provider can produce `site_geometry`.
- **Absent:** Scenario Spec, Isaac, judges, variation and boundary search,
  readiness report, job runtime, API, UI.

### Module dependencies (actual imports)

```text
ir ◄── everything
adapters ◄── reconstruction ◄── context ◄── context_cli, golden_path
provenance ◄── context, validation, routing, trust
validation ◄── context
failure_taxonomy ◄── capabilities, coverage, hypothesis
coverage ◄── hypothesis, investigation, stopping
capabilities ◄── registry, interfaces, graph, routing
registry ◄── interfaces, reference_tools, graph, trust, routing
interfaces ◄── reference_tools, graph, routing
graph ◄── routing
trust ◄── routing
golden_path ──► context, coverage, hypothesis, investigation, graph, registry, reference_tools, routing
knowledge, stopping: imported by nothing in src (library + tests only)
```

### Architectural gaps to be aware of

- The operator session is replay-first and persists its trace outside the
  deployment folder. Hosted LLM output remains optional and bounded by typed
  contracts; the demo does not make a hosted call.
- Deployment IR has no battery or energy fields. Energy enters through
  `constraints` using a unit convention understood only by
  `reference_tools.py`.
- Scene inputs (OBJ/GLB/point clouds) are hashed and summarized, but never
  converted into geometry that an evaluator can consume.
- `validation.ReadinessReport` is context completeness, not the product's
  deployment readiness report.
