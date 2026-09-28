# Product

This document is the canonical product truth for Autonomous Deployment
Verification. Repository instructions live in `AGENTS.md`; implementation
structure lives in `ARCHITECTURE.md`; architectural rationale lives in
`DECISIONS.md`.

## Two-minute explanation

We are building automated pre-deployment verification for drones.

The assumption is that the drone already works. The problem is deciding
whether that known-working drone will successfully carry out a specific
real-world deployment: this site, this route, this payload, this weather, these
rules.

The operator provides deployment information they already have: aircraft
configuration, route, site geometry, operational documents, historical logs,
and environmental context. The system reconstructs the deployment into one
canonical description, tracing every value back to its source. It then
identifies plausible failure mechanisms, such as energy reserve, obstacle
clearance, wind limits, navigation degradation, or visibility. For each one,
it chooses the cheapest model or simulation that can credibly test it,
escalating to high-fidelity simulation (Isaac Sim / Isaac Lab) only when the
answer is close or uncertain. It explores realistic variations such as wind,
battery condition, payload, geometry, navigation degradation, and visibility,
and returns the conditions under which the deployment becomes problematic,
with the evidence behind each claim.

The operator should not need to know which simulator test to configure
manually.

*What exists today* is narrower: reconstruction, applicability, planning, and
analytical evaluation for a hand-supplied hypothesis. See
[`CURRENT_STATE.md`](CURRENT_STATE.md) and run it with [`DEMO.md`](DEMO.md).

## Problem

A drone that works in development can still fail at a particular deployment.
The route may pass too close to site geometry, local wind may exceed control or
energy margins, payload mass may invalidate endurance assumptions, visibility
may undermine a perception capability, or operating constraints may conflict
with the planned mission. These risks are scattered across operator documents,
route files, logs, weather data, site models, controller configuration, and
tribal knowledge.

Pre-deployment verification matters because discovering these mismatches in the
field is expensive and can endanger people, aircraft, property, and the
operation. Existing simulation tools expose powerful mechanisms, but operators
should not have to translate deployment evidence into a hand-authored test plan
or know which simulator and fidelity are credible for each risk.

## Product thesis

Build an autonomous pre-deployment verification platform for **known-working
drones/UAVs**. The system assumes the aircraft and autonomy stack already work
well in their intended operating envelope. It focuses on last-mile deployment
risk rather than basic robotics development.

The core question is:

> Is this known-working drone ready for this specific deployment across the
> plausible conditions it may encounter?

## Target user

The primary user is a drone operator, deployment engineer, or autonomy team
preparing a real mission. They already possess deployment evidence but may not
have simulation expertise. They need a defensible answer, the conditions under
which that answer changes, and a trace back to the evidence and models used.

## Product boundary: drones only

The active product supports drones and UAVs only. Requirements, integrations,
schemas, ontologies, architecture, infrastructure, evaluation logic, and scene
handling must optimize for drone deployments.

Do not add work solely for ground robots, autonomous cars, humanoids,
manipulators, marine robots, or another modality. Cross-modality expansion is a
future phase that begins only after the drone product is complete, validated,
and high quality end to end. Clean reusable abstractions are acceptable when
they arise naturally and do not add scope.

## Intended experience

The primary experience is autonomous investigation, not a text box asking the
operator which test to run. The operator exposes or connects deployment
context. The system then:

1. discovers relevant source material and reconstructs a canonical deployment;
2. identifies plausible deployment-specific failure mechanisms;
3. determines which hypotheses apply and what evidence is still missing;
4. selects the cheapest credible analytical, geometric, learned, physics, or
   simulation capability for each hypothesis;
5. executes deterministic tests and judges their results;
6. escalates suspicious or uncertain cases to higher fidelity, including Isaac
   Sim or Isaac Lab when appropriate;
7. searches for failure boundaries and safe margins rather than sampling only a
   nominal case; and
8. returns a concise readiness assessment backed by evidence, assumptions,
   uncertainty, and reproducible artifacts.

The system may ask for missing information when it cannot establish a credible
answer, but manual test selection is not the main workflow.

## End-to-end flow

An operator begins with existing material such as aircraft and payload
documentation, operations or risk documents, a route, flight logs, weather,
controller configuration, and site geometry. A context agent finds relevant
evidence and deterministic adapters normalize it into Deployment IR.

A failure-hypothesis engine uses that grounded state to propose applicable
risks. A capability registry maps each risk to typed models and tools. The
planner emits a simulator-independent Scenario Spec, and a fidelity router
chooses the least expensive credible backend. Deterministic judges turn outputs
into findings. Adaptive investigation explores uncertainty and failure
boundaries. The final report explains readiness, margins, unresolved risks, and
the provenance behind every material claim.

Post-deployment outcomes may later calibrate future audits for the same
customer. Any learning across customers is separately governed.

## Explicit non-goals

This product is not:

- a generic multi-modality robotics platform;
- a replacement for building or debugging a drone's base autonomy stack;
- a collection of manually invoked simulator workflows;
- a system where an LLM's unsupported judgment establishes pass or fail;
- an Isaac-specific schema or a thin UI over one simulator;
- a scene-acquisition product.

Scene inputs are evidence used by verification. Accept existing meshes, point
clouds, CAD, and GIS first. Historical-image or video reconstruction can be
added later where it materially improves a drone failure evaluation.

## Product success

A successful system reconstructs a deployment from messy existing data with
minimal user effort, autonomously chooses meaningful tests, finds a real safe
margin or failure boundary, and produces a reproducible readiness report. Every
material fact and finding is traceable to evidence, an explicit assumption, or
a model with a stated validity region.
