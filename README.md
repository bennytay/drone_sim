# Autonomous Deployment Verification

Drone-only tooling for reconstructing a deployment from operator data and
verifying whether a known-working UAV is ready for that deployment.

The first milestones establish a canonical, simulator-agnostic Deployment IR,
a read-only local-folder ingestion loop, and first-class evidence for every
material deployment value. The current implementation uses Deployment IR v0.1
inside an evidence envelope v0.1.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Generate the JSON Schema consumed by adapters and downstream services:

```bash
deployment-ir-schema > deployment-ir.schema.json
deployment-evidence-schema > deployment-evidence.schema.json
```

Reconstruct a deployment from a read-only folder. State and output are required
to live outside that folder:

```bash
deployment-context ./operator-data \
  --state ./work/operator-data.state.json \
  --output ./work/evidence-backed-deployment.json
```

The orchestrator indexes file metadata first, then searches for each unresolved
IR field. It opens only ranked files, uses bounded deterministic parsers, and
persists candidate facts, competing values, and an inspection trace so a run
can be resumed without rereading evidence. Completed output includes exact
source anchors, extraction methods, qualitative uncertainty, value origins,
and stable lineage IDs for every populated scalar Deployment IR field. An
optional semantic ranker can augment the built-in lexical search without
receiving file contents.

The adapter registry handles JSON/GeoJSON, summarized CSV, bounded text, PDF,
DOCX, KML, drone telemetry containers, meshes/point clouds, and image/video
metadata. Large streams and binary assets are hashed and summarized; their raw
contents never enter the agent-facing parsed result.

Before output, the CLI applies the drone hypothesis-generation readiness
profile. Missing dependencies, invalid values or units, uncertainty below the
profile threshold, and unresolved conflicts produce a structured readiness
report instead of silently becoming simulation inputs. Library callers can
define additional `EvaluationProfile` contracts for geometry, wind, energy,
perception, or other drone evaluation classes.

See [Deployment IR v0.1 design](docs/deployment-ir-v0.1.md) for the canonical
schema boundary and [Provenance and uncertainty](docs/provenance-v0.1.md) for
the evidence contract. See [Completeness validation](docs/validation-v0.1.md)
for readiness thresholds and conflict handling, and
[Source adapters](docs/source-adapters-v0.1.md) for bounded parsing contracts.
