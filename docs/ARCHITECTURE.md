# Architecture

This document is the canonical current system model. Product intent lives in
`PRODUCT.md`; the reasons behind settled choices live in `DECISIONS.md`.

## System flow

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

## Stages

### Local-folder context agent

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

### Deployment IR

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

### Failure hypothesis engine

The hypothesis engine maps grounded deployment context to plausible failure
mechanisms. LLMs may propose, refine, and prioritize hypotheses, but each
hypothesis must state its applicability, required evidence, causal mechanism,
and testable outcome. Coverage and stopping rules remain explicit.

The hypothesis contract preserves concise causal reasoning as a sequence and
requires deployment-evidence support, an uncertainty basis, candidate test
modalities, and both confirming and falsifying observations. It never lets an
agent assert a quantitative pass/fail threshold; registered deterministic
judges bind observations to versioned criteria.

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

### Capability and model registry

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

### Scenario Spec

Scenario Spec is the simulator- and model-agnostic contract for a test. It
captures initial state, relevant environment, variations, interventions,
observations, and success measures. Backend adapters compile this contract into
tool-specific execution rather than embedding Isaac or another simulator's API
in the canonical spec.

An LLM must not generate arbitrary simulator code in the core path. It chooses
from typed, validated capabilities and parameters.

### Execution backends and fidelity routing

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

### Deterministic judges

Backends emit canonical observations and artifacts. Deterministic judges apply
versioned metrics and thresholds to establish results. LLMs may explain a
finding, but they do not establish the underlying pass, fail, margin, or
measurement.

### Adaptive boundary search

The investigation loop varies causally relevant conditions, searches for the
transition between safe and failing behavior, and allocates fidelity where it
changes the decision. Persistent state tracks explored regions, uncertainty,
coverage, and stopping reasons.

### Readiness report

The report summarizes deployment readiness, safe margins, failure boundaries,
unresolved risks, assumptions, and recommended mitigations. Every material
claim links to source evidence, scenario configuration, model version,
execution artifacts, and judge output.

### Optional post-deployment learning

Observed deployment outcomes can be compared with predictions to measure
residuals and calibrate future audits. Customer-private learning comes first.
Cross-customer learning requires separate governance and must preserve the
validity and provenance of learned updates.

## Responsibility boundary

Agentic components discover context, form hypotheses, plan investigations,
select registered capabilities, decide when to escalate, and summarize results.
Deterministic components parse evidence, validate schemas, execute models and
simulators, compute metrics, judge outcomes, and persist reproducible state.

Provenance and uncertainty cross every stage. A material field or finding must
distinguish observed evidence, deterministic derivation, model output, and
explicit assumption. Conflicts and missing information remain visible rather
than being silently resolved by an LLM.
