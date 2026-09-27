# Completeness validation v0.1

The context agent does not decide informally that a deployment is “good
enough.” It evaluates an evidence-backed Deployment IR against a versioned
`EvaluationProfile` and receives a deterministic `ReadinessReport`.

## Statuses

- `ready`: every declared dependency is present and meets its evidence policy;
- `incomplete`: one or more dependencies are missing;
- `uncertain`: values exist but confidence or approximation origin does not
  meet the profile;
- `conflicting`: contradictory candidates remain without an explicit
  resolution; and
- `invalid`: canonical schema, range, or unit validation failed.

Status precedence is `invalid`, `incomplete`, `conflicting`, `uncertain`, then
`ready`. The report also lists resolved dependencies and structured findings
with paths and candidate IDs. Its `unresolved_paths` property is the next-search
queue for the context agent.

## Evaluation profiles

A profile names a drone evaluation class and lists required exact paths or path
prefixes. Each dependency declares minimum qualitative confidence and which,
if any, inferred, estimated, model-derived, or assumed origins are acceptable.
Approximations are rejected unless the profile explicitly allows their origin.

The built-in `drone_hypothesis_generation_v1` profile requires deployment
identity, drone airframe and mass, mission objective and route, site, autonomy
mode, and success criteria. Later geometry, weather, energy, or perception
evaluators should provide narrower profiles reflecting their causal inputs.

## Conflicts and units

Different candidate values are a conflict even when one was selected for the
canonical IR. They become non-blocking only when `ConflictResolution` names the
method, selected candidate, every rejected candidate, and a rationale. This
prevents file order from masquerading as evidence resolution.

Deployment IR numeric field names encode canonical SI units. Common alternate
aviation units such as feet, pounds, knots, mph, and km/h are invalid at the
canonical boundary; deterministic source adapters must convert them before
validation. Pydantic schema checks continue to enforce numeric ranges.
