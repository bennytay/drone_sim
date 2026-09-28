# Testing

All tests are plain `pytest`, run through `uv`. Each test module is assigned to
exactly one layer in `tests/conftest.py`, which applies a pytest marker.
Collection fails if a new test module is not assigned, and `--strict-markers`
rejects unregistered markers.

```bash
uv sync --extra dev                 # once

uv run pytest                       # everything (what CI runs)
uv run pytest -m component          # component layer
uv run pytest -m integration        # integration layer
uv run pytest -m golden             # Golden Path product test
uv run pytest tests/test_routing.py # one module
uv run pytest tests/test_llm.py     # LLM replay contract tests
uv run pytest tests/test_llm_ledger.py # ledger persistence, replay, and budgets
```

At the time of writing: 131 tests, all passing, in under a second. CI
(`.github/workflows/test.yml`, job `test`) runs `uv run pytest -q` on Python
3.13 for every pull request and every push to `main`.

## Layer 1 — Component tests (`-m component`)

One module or contract in isolation.

| Module | Covers |
|---|---|
| `test_ir.py` | Deployment IR round-trip, schema version, rejection of vendor fields, unique artifact IDs, mass limit |
| `test_provenance.py` | Evidence envelope coverage, value matching, source anchors, assumptions, derivation lineage |
| `test_validation.py` | Readiness statuses, missing/uncertain dependencies, conflict resolution, non-canonical units |
| `test_adapters.py` | CSV, KML, PDF, DOCX, and binary metadata adapters; bounded output; unknown formats rejected |
| `test_failure_taxonomy.py` | Taxonomy completeness, unique IDs, leaf semantics |
| `test_coverage.py` | applies / ruled_out / unknown, coverage state transitions, residual risk |
| `test_hypothesis.py` | Hypothesis contract validation, duplicates, merging |
| `test_knowledge.py` | Knowledge source use and fact precedence |
| `test_llm.py` | Replay-backed Pydantic validation, bounded repair/fail-closed behavior, configuration, and typed tool declarations |
| `test_llm_ledger.py` | Persistent call entries, replay without a provider, input/trace references, usage/cost, and explicit budget stops |
| `test_llm_safety.py` | Adversarial-text delimiting, redaction, disabled-call behavior, ledger payload hashes, and forbidden decision contracts |
| `test_capabilities.py` | Ontology closure, vendor neutrality, mechanism bindings |
| `test_registry.py` | Manifest validation, provider comparison, loading `examples/tool_manifests/` |
| `test_interfaces.py` | Canonical payloads, frame/unit checks, built-in model calculations (energy, clearance with a fixture site) |
| `test_trust.py` | Trust ledger levels, residuals, feedback, confidence caps |
| `test_investigation.py` | Next-action selection and escalation |
| `test_stopping.py` | Stop on budget and on disagreement |

## Layer 2 — Integration tests (`-m integration`)

Several components wired together.

| Module | Flow |
|---|---|
| `test_context.py` | Folder → index → adapters → candidates → evidence-backed IR; resume, conflicts, stale versus current files, clarification requests |
| `test_synthetic_deployments.py` | Six generated folders in `examples/synthetic_deployments/` → orchestrator → expected readiness (ready, conflicting, incomplete, invalid) |
| `test_graph.py` | Hypothesis → `EvaluationGoal` → `GraphPlanner` → `execute` with built-in providers → measures with lineage; gaps, failures, reproducibility |
| `test_routing.py` | Goal → `FidelityRouter` → accept, escalate, exhausted, or disagreement across fidelity levels (uses stub providers) |

## Layer 3 — Golden Path product test (`-m golden`)

`test_golden_path.py` runs `drone-eval analyse examples/demo_deployment
--hypotheses examples/demo_hypotheses.json` in-process and asserts:

- the demo folder reconstructs to a `READY` evidence-backed IR, with the exact
  source anchor for vehicle mass, and is left unmodified;
- every hypothesised mechanism is `applies` in the coverage map;
- the energy-reserve hypothesis is planned, executed, and accepted at
  analytical fidelity, with the reserve threshold derived as 36 Wh;
- the mass-margin result is currently `unquantified` (known defect 2 in
  `CURRENT_STATE.md`; update the test when it is fixed);
- the clearance hypothesis stops on a `site_geometry` planning gap;
- rendered output labels the stand-ins and unimplemented stages;
- CLI exit codes: `0` for the demo, `2` for a conflicting folder, and `1` for a
  work directory inside the analysed folder.

## What is not tested

These have no executable tests because they do not exist yet. Do not describe
them as tested: hypothesis generation, Scenario Spec, Isaac Sim/Lab, judges,
scenario variation and boundary search, the readiness report, job runtime,
API, and UI. The Isaac manifest is validated only as registry metadata. The
closed-loop and high-fidelity paths in `test_graph.py` and `test_routing.py`
use in-process **stubs**, not simulators.

## Hosted LLM smoke test

The component tests are replay-only and make no network calls. To check the
configured Anthropic edge against the hosted provider, use a non-production,
least-privilege API key and run:

```bash
ANTHROPIC_API_KEY=... uv run drone-llm-smoke
```

Optional settings are `DRONE_SIM_LLM_EXTRACTION_MODEL`,
`DRONE_SIM_LLM_HYPOTHESIS_MODEL`, `DRONE_SIM_LLM_TIMEOUT_S`, and
`DRONE_SIM_LLM_RETRIES`. With no key, the command fails before a network call
with a clear configuration message; the existing deterministic pipeline does
not invoke this command or an LLM.

## Adding tests

- Put a new module in the right layer in `tests/conftest.py`.
- A change that alters Golden Path output must update `test_golden_path.py`
  and `docs/DEMO.md` together.
- Shared fixtures are imported between test modules (e.g.
  `from test_interfaces import demo_deployment`). Keep them import-safe.
