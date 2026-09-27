# Context reconstruction v0.1

The reconstruction loop converts differently organized drone deployment
folders into the same evidence-backed Deployment IR. It does not require a
canonical manifest filename or directory layout.

## Dependency templates

Each canonical top-level field has a reusable `DependencyTemplate` containing:

- relevance query terms;
- deterministic source aliases;
- preferred artifact suffixes;
- whether the field is required; and
- the clarification question to ask only after search exhaustion.

The initial templates cover deployment identity, aircraft, payloads, mission
and route, site, conditions, autonomy, constraints, success criteria,
telemetry, raw observations, and models. Alias normalization maps common drone
operator labels such as `aircraft`, `flight_plan`, `operating_site`, and
`flight_control` into canonical values. Each normalized scalar retains its
actual source JSON Pointer rather than a synthesized canonical pointer.

## Search and evidence ranking

The metadata index ranks path-token overlap, an optional semantic ranker,
artifact formats preferred by the unresolved dependency, and explicit filename
signals. `current`, `approved`, `final`, `release`, and `signed` are preferred;
`archive`, `backup`, `old`, `obsolete`, and `superseded` are demoted. Ranking
chooses the provisional canonical candidate but never discards alternatives;
different values still trigger deterministic conflict validation.

Poorly named files remain discoverable through format-aware structured
fallbacks. Once a candidate is found, unrelated low-signal files are not opened.
Parsed bounded results are cached in persistent state and reused across
dependency searches. Added, removed, resized, or modified files invalidate the
affected cache and candidates and reopen unresolved searches.

## Entity links and clarification

Repeated deployment, vehicle, and site identifiers link evidence across JSON,
documents, indexes, and logs. Links store the normalized identity and every
source path; they do not merge values or override conflicts.

`clarification_requests` is the final fallback. It is populated only for a
material unresolved path whose dependency search has completed. Each request
records the canonical field, targeted operator question, reason, and already
searched paths. New evidence can be added to the folder and the same persisted
analysis resumed; index invalidation causes the relevant dependencies to be
searched again.
