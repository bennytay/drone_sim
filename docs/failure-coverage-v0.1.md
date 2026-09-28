# Failure applicability and coverage v0.1

`drone_sim.coverage` evaluates the versioned drone failure taxonomy against a
canonical `DeploymentIR`. It produces a `CoverageMap` with one auditable entry
per mechanism and a residual unknown-risk record.

## Applicability is not coverage

Each mechanism profile defines prerequisites, deterministic activation and
deactivation predicates, materiality, and viable test modalities. A predicate
uses a stable Deployment IR JSON Pointer and a comparison. Results are
preserved with the observed value and readable reason.

- **applies** means every activation condition is supported and no
  deactivation condition holds; it starts **unexamined**.
- **ruled out** means evidence contradicts a required activation condition or
  explicitly deactivates the mechanism; it has **ruled_out** coverage.
- **unknown** means the evidence needed to decide is absent; it has
  **uncertain** coverage. Missing evidence is never treated as irrelevance.

Only applicable mechanisms can transition through deterministic investigation:
`unexamined` to `tested`, `uncertain`, or `escalated`. A test result records
its reason but does not hide the original applicability evidence.

## Meaningful coverage

Coverage means each known mechanism is explicitly accounted for, not that the
deployment is proven safe. A map retains unexamined, uncertain, and escalated
entries as unexplored work. `residual_unknowns` represents known limitations
such as taxonomy gaps; it is a first-class output rather than an implied
absence of risk.

The default profiles are deliberately conservative baseline rules generated
from leaf context dependencies. They provide an exhaustive ledger for the
current catalog. Specialized, versioned profiles can later add mechanism-
specific activation thresholds based on validated model or regulatory evidence.
