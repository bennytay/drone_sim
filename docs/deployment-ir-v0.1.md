# Deployment IR v0.1 design

Deployment IR describes one planned drone deployment: the aircraft and payload,
mission intent, operating site and conditions, autonomy mode, constraints,
success criteria, and references to supporting bytes or models.

## Boundary

The canonical layer owns concepts that an evaluator needs regardless of source
or execution backend. Source adapters own vendor field names, log formats,
coordinate conversions, and defaults. Simulation adapters own backend-specific
asset configuration. Neither belongs in the IR.

The schema separates three kinds of information:

- facts are typed deployment fields such as vehicle mass or wind speed;
- constraints state operational limits without prescribing their evaluator;
- model and artifact references point to external bytes without embedding their
  source or simulator semantics.

Static deployment metadata is stored directly. Time-series and large binary
data remain external and are represented by `ArtifactRef`. This keeps the IR
small enough to inspect, validate, persist, and pass between services.

## Versioning

`schema_version` is a required literal with current value `0.1.0`. Unknown
fields and unknown versions fail validation. Adapters must explicitly migrate
their output when the schema changes.

Version 0.1 intentionally does not model provenance, confidence, conflicts, or
completeness. Those are state around candidate facts and become first-class in
milestone 2; adding them prematurely would couple the canonical deployment to
the ingestion workflow.

## Deliberate omissions

- vendor-specific vehicle, route, controller, and log fields;
- simulation engine settings and scene graph details;
- generalized concepts for non-drone robots;
- a universal units or ontology system;
- embedded telemetry samples, meshes, or other large data.

These boundaries should be revisited only from concrete evaluation needs.
