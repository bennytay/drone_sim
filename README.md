# Autonomous Deployment Verification

Drone-only tooling for reconstructing a deployment from operator data and
verifying whether a known-working UAV is ready for that deployment.

The first milestone establishes a canonical, simulator-agnostic Deployment IR
and a read-only local-folder ingestion loop. The current implementation starts
with Deployment IR v0.1.

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
```

Reconstruct a deployment from a read-only folder. State and output are required
to live outside that folder:

```bash
deployment-context ./operator-data \
  --state ./work/operator-data.state.json \
  --output ./work/deployment-ir.json
```

The orchestrator indexes file metadata first, then searches for each unresolved
IR field. It opens only ranked files, uses bounded deterministic parsers, and
persists both candidate facts and an inspection trace so a run can be resumed
without rereading evidence. An optional semantic ranker can augment the built-in
lexical search without receiving file contents.

See [Deployment IR v0.1 design](docs/deployment-ir-v0.1.md) for the canonical
schema boundary and deliberate omissions.
