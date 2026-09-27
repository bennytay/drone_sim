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

Version 0.1 intentionally does not embed provenance, confidence, conflicts, or
completeness in each canonical field. Those concerns are first-class in the
versioned `EvidenceBackedDeployment` envelope described in
[`provenance-v0.1.md`](provenance-v0.1.md). Keeping the envelope separate lets
downstream stages consume canonical values while retaining their evidence graph
without coupling Deployment IR semantics to one ingestion workflow.

## Deliberate omissions

- vendor-specific vehicle, route, controller, and log fields;
- simulation engine settings and scene graph details;
- generalized concepts for non-drone robots;
- a universal units or ontology system;
- embedded telemetry samples, meshes, or other large data.

These boundaries should be revisited only from concrete evaluation needs.
