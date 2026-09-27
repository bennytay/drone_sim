# Architecture

This document is the canonical current system model. Product intent lives in
`PRODUCT.md`; the reasons behind settled choices live in `DECISIONS.md`.

## System flow

```text
local-folder context agent
  -> Deployment IR
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

### Deployment IR

Deployment IR is the canonical description of deployment reality and intent:
vehicle, payload, mission, route, environment, conditions, autonomy,
constraints, success criteria, telemetry references, and attached model
references. It is typed, versioned, and independent of DJI, PX4, Isaac, or any
other vendor or backend.

Source adapters translate source-specific semantics into Deployment IR. They do
not leak their native field names into the canonical representation.

### Failure hypothesis engine

The hypothesis engine maps grounded deployment context to plausible failure
mechanisms. LLMs may propose, refine, and prioritize hypotheses, but each
hypothesis must state its applicability, required evidence, causal mechanism,
and testable outcome. Coverage and stopping rules remain explicit.

### Capability and model registry

The registry describes available parsers, analytical models, geometry checks,
learned models, physics tools, simulators, and judges through typed inputs,
outputs, cost, fidelity, validity region, and evidence requirements. Canonical
capabilities are separate from vendor implementations so a backend can be
replaced without changing test intent.

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
