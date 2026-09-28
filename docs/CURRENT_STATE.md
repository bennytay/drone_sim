# Current state

This document records what the repository **actually does today**. It is
derived from reading the code and running it, not from design documents.
Intended behavior lives in [`ARCHITECTURE.md`](ARCHITECTURE.md#intended-architecture);
when the two disagree, this file describes reality.

- **Audited at:** `b2f7e81` (BEN-17) plus the Golden Path layer added on top.
- **Test suite at audit:** 146 passing (`uv run pytest`).
- **See it run:** [`DEMO.md`](DEMO.md). **Test layers:** [`TESTING.md`](TESTING.md).

Legend: ✅ implemented and working · 🟡 partial · ⚪ planned / not
implemented · 🔴 broken or known defect.

## One-paragraph summary

Given a folder of drone deployment files, the code can deterministically
reconstruct an evidence-backed Deployment IR, where every value is traced to an
exact source location. It can then decide whether that context is complete
enough to reason about, and mark which of 32 catalogued drone failure
mechanisms have the context they need. Given a hand-written hypothesis, it can
plan and run a chain of built-in models: an analytical energy-reserve model,
and a mass-envelope check. It routes each result across fidelity levels with
written justifications. It **cannot** yet generate hypotheses, judge
pass/fail, vary conditions, search for failure boundaries, run Isaac, or
produce a readiness report. The LLM provider edge is implemented but is not
wired into a product stage; without `ANTHROPIC_API_KEY`, all product behavior
remains deterministic.

## Status table

| Component | Status | Code | Tests |
|---|---|---|---|
| Local-folder context ingestion | ✅ | `context.py` | `test_context.py`, `test_synthetic_deployments.py` |
| Parsers / source adapters | ✅ | `adapters.py` | `test_adapters.py` |
| Deployment IR | ✅ | `ir.py`, `schema.py` | `test_ir.py` |
| Provenance and uncertainty | ✅ | `provenance.py`, `evidence_schema.py` | `test_provenance.py` |
| Conflict and completeness validation | ✅ detection · 🟡 resolution | `validation.py` | `test_validation.py`, `test_context.py` |
| Failure taxonomy | ✅ | `failure_taxonomy.py` | `test_failure_taxonomy.py` |
| Applicability / coverage map | 🟡 | `coverage.py` | `test_coverage.py` |
| Hypothesis contract | ✅ | `hypothesis.py` | `test_hypothesis.py` |
| LLM provider edge + call ledger | ✅ | `llm.py`, `llm_ledger.py`, `llm_cli.py` | `test_llm.py`, `test_llm_ledger.py` |
| LLM safety boundary | ✅ | `llm_safety.py` | `test_llm_safety.py` |
| LLM evaluation harness | 🟡 replay baseline | `llm_eval.py`, `llm_eval_cli.py` | `test_llm_eval.py` |
| Hypothesis **generation** | ⚪ | — | — |
| Knowledge enrichment | 🟡 contract only | `knowledge.py` | `test_knowledge.py` |
| Capability ontology + mechanism bindings | ✅ | `capabilities.py` | `test_capabilities.py` |
| Tool / model registry | ✅ | `registry.py`, `examples/tool_manifests/` | `test_registry.py` |
| Canonical payloads + tool adapter base | ✅ | `interfaces.py` | `test_interfaces.py` |
| Scenario IR / Scenario Spec | ⚪ | — | — |
| Analytical models | 🟡 | `reference_tools.py` | `test_interfaces.py`, `test_graph.py` |
| Geometry evaluation | 🟡 | `reference_tools.py` (`SweptVolumeClearance`) | `test_graph.py` (with a test-only site provider) |
| Capability graph planning + execution | ✅ | `graph.py` | `test_graph.py` |
| Fidelity routing / escalation | ✅ | `routing.py` | `test_routing.py` |
| Model trust ledger | 🟡 | `trust.py` | `test_trust.py` |
| Isaac Sim / Isaac Lab integration | ⚪ | manifest JSON only | — |
| Scenario generation | ⚪ | — | — |
| Deterministic judges | ⚪ | — | — |
| Investigation policy | 🟡 unwired · 🔴 ordering bug | `investigation.py` | `test_investigation.py` |
| Stopping policy | 🟡 unwired | `stopping.py` | `test_stopping.py` |
| Boundary / scenario search | ⚪ | — | — |
| Readiness report (deployment verdict) | ⚪ | — | — |
| Post-deployment learning / calibration | 🟡 ledger only | `trust.py` | `test_trust.py` |
| Runtime / job infrastructure | ⚪ | — | — |
| CLI | 🟡 | `context_cli.py`, `schema.py`, `evidence_schema.py`, `golden_path.py` | `test_golden_path.py` |
| API / UI | ⚪ | — | — |

All paths are under `src/drone_sim/` unless stated.

## Component details

### Local-folder context ingestion — ✅

- **What it does:** indexes a read-only folder by metadata. For each
  Deployment IR top-level field, it ranks files using lexical path overlap,
  preferred suffixes, and current/stale filename signals, then opens ranked
  files through adapters. It extracts candidates through deterministic
  aliases, links entity IDs across files, and persists state (candidates,
  parsed summaries, trace) outside the folder so a rerun resumes.
- **Where:** `context.py` (`DirectoryIndex`, `DeterministicFileReader`,
  `StateStore`, `ContextOrchestrator`) and `reconstruction.py` (dependency
  templates, alias normalization, entity links, clarification requests).
- **Called by:** `context_cli.py` (`deployment-context`) and `golden_path.py`
  (`drone-eval`).
- **Calls:** `adapters.py`, `reconstruction.py`, `provenance.py`,
  `validation.py`.
- **Run:** `uv run deployment-context examples/demo_deployment --state /tmp/s.json`
- **Test:** `uv run pytest tests/test_context.py tests/test_synthetic_deployments.py`
- **Limitations:**
  - The "context agent" is a deterministic search loop. There is no LLM.
    `SemanticRanker` is a protocol with no implementation.
  - Only JSON and GeoJSON content can become IR values. PDF, DOCX, Markdown,
    and text are used only for entity linking. CSV, KML, logs, and meshes
    become metadata summaries.
  - Route geometry in GeoJSON or KML is **not** converted into
    `mission.route`. The route must appear as waypoint objects inside a JSON
    file.
  - Every candidate gets `origin=observed`, `confidence=medium`, and
    extraction version `"1"`. Confidence is not derived from the source.
  - In small folders nearly every file is opened (the demo opens 15/15).

### Parsers / source adapters — ✅

- **What it does:** suffix-dispatched, bounded, deterministic parsing into a
  common `ParsedSource`. JSON/GeoJSON is parsed fully (up to a size limit).
  CSV is streamed into columns, samples, and numeric ranges. Text, PDF, and
  DOCX yield bounded text. KML yields coordinate bounds and samples.
  ULog/TLog/BIN/MCAP/bag, OBJ/PLY/PCD/LAS/GLB, PNG/JPG, and MP4/MOV yield
  metadata and hashes only.
- **Where:** `adapters.py`. **Called by:** `context.py`.
- **Test:** `uv run pytest tests/test_adapters.py`
- **Limitations:** no flight-log decoding (ULog gives only its header
  timestamp), no mesh geometry extraction, no image EXIF/geo metadata.
  Unknown suffixes fail closed.

### LLM provider edge and call ledger — ✅ (not yet wired into an agent)

- **What it does:** defines provider-neutral messages, versioned prompts, typed
  tool schemas, normalized responses, task-selected model IDs, environment
  configuration, and an Anthropic Messages API adapter. `StructuredOutputRunner`
  parses returned JSON directly into any existing Pydantic contract, feeds
  validation errors back for a bounded repair count, then raises an explicit
  failure. An atomic persistent ledger fingerprints each request, records model,
  prompt version/hash, input references (candidate IDs/file hashes), context
  trace indices, response, usage, latency, cost, validation result, and whether
  it was live or replayed. Per-stage budgets stop explicitly; replay cannot
  fall through to a hosted request. It cannot establish a readiness result or
  call arbitrary simulator code.
- **Where:** `llm.py`, `llm_ledger.py`; the live configuration check is
  `llm_cli.py`.
- **Run:** `ANTHROPIC_API_KEY=... uv run drone-llm-smoke`.
- **Test:** `uv run pytest tests/test_llm.py tests/test_llm_ledger.py` (no
  network call).
- **Limitations:** retention and customer-data/prompt-injection policy remain
  BEN-66; no evaluation harness (BEN-67), and no product stage consumes this
  client yet.

### Deployment IR — ✅

- **What it does:** a strict, versioned (`0.1.0`), vendor-neutral Pydantic
  model covering vehicle, payloads, mission and route, site, conditions,
  autonomy, constraints, success criteria, and artifact/model references.
- **Where:** `ir.py`. JSON Schema: `uv run deployment-ir-schema`.
- **Called by:** almost every module.
- **Test:** `uv run pytest tests/test_ir.py`
- **Limitations:**
  - No battery or energy fields. Usable energy and reserve fraction are
    expressed as `constraints` with `category: energy` and units `Wh` / `1`.
    Only `reference_tools.py` understands this convention.
  - Only one route. There are no contingency routes, geofence polygons, or
    landing zones as geometry.
  - Artifact URIs are not checked against the folder.

### Provenance, conflicts, and completeness — ✅ detection, 🟡 resolution

- **What it does:** `EvidenceBackedDeployment` requires one `MaterialFact`
  per populated scalar IR leaf, with source anchor, SHA-256, extraction
  method, qualitative confidence, and competing candidates. It rejects
  missing coverage, dangling assumptions, and derivation cycles.
  `assess_evidence`/`assess_values` return `ready`, `incomplete`,
  `uncertain`, `conflicting`, or `invalid` against an `EvaluationProfile`.
  Only `drone_hypothesis_generation_v1` is built in.
- **Where:** `provenance.py`, `validation.py`.
- **Test:** `uv run pytest tests/test_provenance.py tests/test_validation.py`
- **Limitations:** the orchestrator never creates a `ConflictResolution` or
  an `Assumption`, and no CLI lets an operator resolve a conflict. A folder
  with contradictory values therefore stops the pipeline permanently until
  its files change. Note the naming: `validation.ReadinessReport` is **context
  completeness**, not the deployment-readiness report the product promises.

### Failure taxonomy — ✅

- **What it does:** a versioned tree of 10 drone failure domains and 32
  testable leaf mechanisms. Each leaf has causal variables, observable
  outcomes, and the IR paths it needs.
- **Where:** `failure_taxonomy.py`. **Test:** `uv run pytest tests/test_failure_taxonomy.py`

### Applicability / coverage map — 🟡

- **What it does:** `assess_coverage(deployment)` evaluates each mechanism
  as `applies`, `ruled_out`, or `unknown` from deterministic predicates. It
  records the evidence and keeps a residual `taxonomy_gap` risk.
- **Where:** `coverage.py`. **Called by:** `golden_path.py`, tests.
- **Test:** `uv run pytest tests/test_coverage.py`
- **Limitations:** the only profiles are `default_profiles()`. These say "applies if
  every required IR path exists", so a complete IR makes nearly everything
  apply: the demo gives 31 of 32. Nothing yet rules a mechanism out on
  deployment facts (for example, no precipitation means precipitation is ruled
  out). Materiality and testability come from substring heuristics on the ID.

### Hypothesis contract — ✅ · hypothesis generation — ⚪

- **What exists:** `FailureHypothesis` and `HypothesisGenerationContract`
  (validation, duplicate keys, `merge_duplicates`). `knowledge.py` defines
  source provenance and fact/prompt precedence.
- **What does not exist:** anything that *produces* hypotheses. No module
  turns an IR or coverage map into `FailureHypothesis` objects. A contract-
  validated Anthropic provider edge now exists but is not wired here.
  `KnowledgeBundle` is used by nothing except its test. The
  Golden Path loads `examples/demo_hypotheses.json` (hand-written) instead.
- **Test:** `uv run pytest tests/test_hypothesis.py tests/test_knowledge.py`

### Capability ontology, registry, and payloads — ✅

- **What it does:** `capabilities.py` defines tool-independent capabilities
  (e.g. `energy.route_demand`, `geometry.route_clearance`) and binds every
  taxonomy leaf to a minimum capability set. `registry.py` validates
  `ToolManifest`s and compares providers per capability and operating context:
  validity region, fidelity, and cost. `interfaces.py` defines one typed
  payload per data kind (ENU frame, SI units) and the `ToolAdapter` base class.
- **Called by:** `graph.py`, `routing.py`, `reference_tools.py`, `golden_path.py`.
- **Test:** `uv run pytest tests/test_capabilities.py tests/test_registry.py tests/test_interfaces.py`
- **Limitations:** the five manifests in `examples/tool_manifests/`
  (including `isaac.closed-loop-flight`) are **metadata only**. They load
  into a registry, but no adapter code backs them. If they were registered
  for execution, the planner could pick them and execution would fail with
  "no adapter bound".

### Analytical models — 🟡

- **What exists** (`reference_tools.py`, the only executable providers):
  - `DeploymentSemantics` (rule fidelity): IR to route in a local ENU frame,
    vehicle envelope and mass margin, ISA-style atmosphere, and uniform wind.
  - `MomentumEnergy` (analytical, multirotor, wind 0–12 m/s): momentum-theory
    hover power plus parasitic drag and climb, integrated per leg; ±15%
    declared error. Produces remaining energy and a reserve breach flag.
- **Test:** `uv run pytest tests/test_interfaces.py tests/test_graph.py`
- **Limitations:** energy covers transit legs only. There is no
  hover or capture time at waypoints, so the demo's 900 s planned mission is
  modelled as about 56 s and 8.6 Wh. Coefficients (figure of merit 0.6, drag
  coefficient 1.0) are uncalibrated constants. Wind is uniform and steady.

### Geometry evaluation — 🟡

- **What exists:** `SweptVolumeClearance` samples the route and measures
  distance from the vehicle's extent to axis-aligned box obstacles and the
  ground.
- **Limitation:** it needs a `SiteGeometry` payload, and **no production
  provider creates one**. OBJ/GLB/point-cloud files are summarized as
  metadata, and nothing turns them into obstacles. Only the test fixture
  `SurveyedSite` in `tests/test_interfaces.py` supplies boxes. In the Golden
  Path, the clearance hypothesis therefore stops at planner gaps.

### Capability graph planning and execution — ✅

- **What it does:** `GraphPlanner` backward-chains from a goal's measures
  through mechanism bindings to providers. The result is an acyclic
  `ExecutionPlan` that lists explicit gaps. `execute` runs nodes in-process
  and records input/output digests, lineage, failures, skipped nodes, and
  per-measure uncertainty sources.
- **Where:** `graph.py`. **Test:** `uv run pytest tests/test_graph.py`
- **Limitations:** execution is in-process only. `ExecutionMode.remote_service`
  and `local_process` are declared in manifests but never implemented.

### Fidelity routing — ✅

- **What it does:** `FidelityRouter.investigate` plans at the lowest
  eligible fidelity and executes. It then compares each decision measure's
  margin with `boundary_factor × error` and either accepts, escalates the
  producing capability one fidelity class, or reports `exhausted`. It flags
  cross-level disagreement for review. Floors force closed-loop and
  sensor-realism mechanisms to high-fidelity simulation.
- **Where:** `routing.py`. **Test:** `uv run pytest tests/test_routing.py`
- **Limitations:** the caller must supply `DecisionThreshold`s, because no
  judge produces them. `accept` means "this fidelity is credible", **not**
  "the deployment passes". Escalation can only reach providers that
  exist; in practice there is nothing above analytical.

### Model trust ledger / post-deployment learning — 🟡

- **What exists:** `TrustLedger` holds per-model-version validation datasets,
  residual statistics, unsupported regions, and `record_outcome` feedback. It
  classifies an operating point as validated, extrapolated, unvalidated, or
  unsupported, and caps confidence. `FidelityRouter` accepts an optional ledger.
- **Missing:** outcome schema and log ingestion (BEN-42/43), persistence of
  the ledger, and customer calibration workflows (BEN-44/45). The Golden
  Path runs without a ledger.
- **Test:** `uv run pytest tests/test_trust.py`

### Investigation and stopping policies — 🟡 (unwired), 🔴 one defect

- **What exists:** `investigation.next_action` picks the highest-materiality
  unresolved hypothesis and proposes test, escalate, refine, follow-up, or
  resolve. `stopping.decide_stop` stops on budget, disagreement, or
  completion and lists residual mechanisms.
- **Missing:** a loop that runs actions, converts routing outcomes into
  `TestResult`s, and calls `decide_stop`. The Golden Path shows only the
  first `next_action`.
- **Test:** `uv run pytest tests/test_investigation.py tests/test_stopping.py`

### Not implemented — ⚪

| Component | Planned in | What exists instead |
|---|---|---|
| Scenario Spec / Scenario IR | BEN-24 | `EvaluationGoal` + `OperatingContext` (measures plus a wind variable) |
| Isaac Sim adapter | BEN-25 | `examples/tool_manifests/isaac_closed_loop.json` (metadata) and test stubs |
| Isaac Lab scenario generation | BEN-26/27 | nothing |
| Closed-loop autonomy connection | BEN-28 | nothing |
| Scene pipeline (assets to USD) | BEN-30–33 | adapters summarize meshes as metadata |
| Canonical run results, judges | BEN-36/37 | router margin check against caller-supplied thresholds |
| Scenario exploration, boundary search | BEN-38/39 | nothing; one nominal condition only |
| Readiness report model and generator | BEN-40/41 | nothing |
| Outcome schema, log ingestion | BEN-42/43 | `TrustLedger.record_outcome` API only |
| Job / run model, orchestration, workers | BEN-48/49, 52–55 | JSON state file for context reconstruction only |
| Customer journey, upload UX, workspace UI | BEN-58–63 | CLI only |

### CLI — 🟡

| Command | Does |
|---|---|
| `uv run drone-eval analyse <folder> [--hypotheses F]` | Golden Path: every implemented stage, human-readable output, JSON artifacts in `./work/<folder>` |
| `uv run deployment-context <folder> --state S [--output O]` | Context reconstruction only; prints evidence JSON, or a readiness report and clarifications on stderr with exit 1 |
| `uv run deployment-ir-schema` / `deployment-evidence-schema` | Print JSON Schemas |

## Known defects and inconsistencies

1. 🔴 **Hypothesis priority ordering.** `investigation.next_action` breaks
   materiality ties with `uncertainty.value`, which is a string, so the order is
   alphabetical: `medium` > `low` > `high`. A high-uncertainty hypothesis is
   chosen *last* among equals. Reproduced during this audit; not fixed.
2. 🔴 **Exact rule outputs cannot be accepted.** `graph.py` treats
   rule-fidelity providers as exactly quantified, but `routing.py` needs a
   numeric error width. The demo's mass margin (+1.48 kg, computed exactly)
   is therefore reported `unquantified` / `exhausted` / "review required".
   `tests/test_golden_path.py` pins this current behavior.
3. **Linear status vs. code.** BEN-12 to BEN-23 are Done in Linear, and each
   landed a contract or policy with unit tests. Several
   "Build …" issues (BEN-16 investigation policy, BEN-21 graph execution)
   delivered library functions that no product path called until the
   Golden Path wired some of them.
4. **Architecture doc presented the whole pipeline as current.** Fixed by
   splitting `ARCHITECTURE.md` into *Intended* and *Current implementation*.
5. **README claim.** It said built-in providers run "an analytical
   energy-reserve and route-clearance graph end to end". Clearance runs only
   with a test-fixture site provider. README corrected.
6. **Two meanings of "readiness".** `validation.ReadinessReport` is context
   completeness; the product's readiness report does not exist yet.
7. **Energy is a constraint.** Battery capacity has no IR home (see Deployment
   IR limitations).

## Keeping this file honest

Update this file in the same change as any behavior change (see the
Definition of Done in `AGENTS.md`). Do not change a status to ✅ unless a
test or the Golden Path exercises it.
