# Last-mile drone failure taxonomy v0.1

The canonical taxonomy is a versioned fault tree for asking what can make a
known-working drone unsuitable for one deployment. It is failure knowledge, not
a checklist asserting that every branch applies. Applicability and coverage are
separate concerns so the planner can rule branches out with evidence instead of
defaulting to “test everything.”

## Boundary

The taxonomy includes failures caused or activated by the deployment: site
geometry, plausible weather, configured payload and mass, route and mission,
local sensing and communications conditions, operating constraints, and
external actors. It explicitly excludes unfinished autonomy, generic software
correctness, unindicated manufacturing defects, and basic airframe design work.
Those are upstream development concerns unless deployment evidence supplies a
specific causal trigger.

## Hierarchy

`FailureTaxonomy` contains exactly one category for each required drone domain:

1. environment and weather;
2. energy and battery;
3. geometry and clearance;
4. vehicle operating envelope;
5. navigation and localization;
6. perception and sensing;
7. communication;
8. mission execution;
9. operational, site, and regulatory constraints; and
10. deployment-specific external actors.

Categories contain intermediate branches and testable leaves. Stable dotted
IDs preserve identity across runs. Every leaf records:

- causal variables that a hypothesis or test may vary;
- observable outcomes a deterministic backend can emit;
- Deployment IR paths needed to establish relevance; and
- deployment tags that identify common and specialized contexts.

Tags are discovery aids, not sufficient applicability evidence. BEN-13 defines
the rules and audit state that activate, deactivate, or leave branches unknown.
Likewise, the listed outcomes do not contain pass/fail thresholds. A later
hypothesis and deterministic judge must bind them to deployment constraints and
success criteria.

## Representative coverage

The default catalog includes common surfaces plus mechanisms relevant to urban,
BVLOS, delivery, mapping, inspection, industrial, indoor, coastal, rural, and
high-altitude operations. This breadth supports representative deployments
while retaining narrow mechanisms such as GNSS multipath, vertical-datum
mismatch, landing-zone incompatibility, payload link saturation, unsuitable
failsafes, and temporary obstacles.

Consumers should select mechanisms through explicit applicability evidence,
not execute all leaves. An absent applicable failure finding is not proof of
safety, and taxonomy coverage is not exhaustive assurance.
