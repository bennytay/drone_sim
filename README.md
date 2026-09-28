# Autonomous Deployment Verification

Drone-only tooling for reconstructing a deployment from operator data and
verifying whether a known-working UAV is ready for that deployment.

The first milestones establish a canonical, simulator-agnostic Deployment IR,
a read-only local-folder ingestion loop, and first-class evidence for every
material deployment value. The current implementation uses Deployment IR v0.1
inside an evidence envelope v0.1.

Failure discovery starts from a versioned, drone-only last-mile taxonomy. Its
fault-tree leaves carry causal variables, observable outcomes, and required
Deployment IR context while keeping deployment applicability and deterministic
pass/fail judgments separate.

The taxonomy is evaluated as an evidence-backed coverage map: a mechanism can
be applicable and unexamined, ruled out by context, or uncertain because
required evidence is missing. Residual unknown risks remain visible rather
than being treated as safety proof.

Each taxonomy mechanism is expressed as a minimum set of canonical
capabilities, such as route energy demand or trajectory clearance, drawn from a
tool-independent capability ontology. Capabilities declare typed inputs,
outputs, and measures but never name a simulator or vendor model.

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

Reconstruction uses reusable dependency templates, canonical aliases, ranked
current-versus-stale evidence, cached parsed summaries, and cross-file entity
links. If exhaustive evidence search still leaves a material gap, the CLI
returns targeted clarification requests alongside the readiness report.

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
The broader search and linking loop is documented in
[Context reconstruction](docs/context-reconstruction-v0.1.md). See
[Failure taxonomy v0.1](docs/failure-taxonomy-v0.1.md) for the discovery
surface and its product boundary,
[Failure coverage v0.1](docs/failure-coverage-v0.1.md) for applicability and
investigation-state semantics, and
[Capability ontology v0.1](docs/capability-ontology-v0.1.md) for how
hypotheses become capability requirements.

## Synthetic QA corpus

Six reproducible fictional deployment folders live under
`examples/synthetic_deployments`. They cover clean, renamed/messy,
conflicting, incomplete, split-file, and invalid-unit outcomes and include
representative GeoJSON, KML, CSV telemetry, ULog/MCAP headers, DOCX, PNG, and
OBJ artifacts. They are test data only and must never authorize a real flight.

Regenerate them deterministically with:

```bash
uv run python tools/generate_fake_deployments.py \
  --output examples/synthetic_deployments \
  --seed 20260928 \
  --count 6 \
  --force
```

The corpus manifest declares the expected readiness of each folder, and the
test suite runs every folder through the real context orchestrator.
