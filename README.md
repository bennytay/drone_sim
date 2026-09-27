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

See [Deployment IR v0.1 design](docs/deployment-ir-v0.1.md) for the canonical
schema boundary and [Provenance and uncertainty](docs/provenance-v0.1.md) for
the evidence contract.
