# Golden Path demo

One command runs every stage of the product that exists today on one fictional
drone deployment, prints the intermediate state, and says exactly where the
pipeline stops. What is real and what is not is summarized in the
[table below](#what-is-real-and-what-is-not); full detail is in
[`CURRENT_STATE.md`](CURRENT_STATE.md).

## 1. Prerequisites

- [`uv`](https://docs.astral.sh/uv/). CI uses Python 3.13; `pyproject.toml`
  requires Python 3.11 or newer.
- A checkout of `main` that is up to date (`git pull`).
- Install once from the repository root:

```bash
uv sync --extra dev
```

No GPU, network access, Isaac installation, or API key is needed. No LLM is
called.

## 2. Run it

```bash
uv run drone-eval analyse examples/demo_deployment --hypotheses examples/demo_hypotheses.json
```

Useful variants:

```bash
# Every mechanism and every routing justification
uv run drone-eval analyse examples/demo_deployment --hypotheses examples/demo_hypotheses.json --verbose

# Without hypotheses: stops honestly after the applicability map
uv run drone-eval analyse examples/demo_deployment

# A folder with contradictory evidence: stops at the readiness gate (exit code 2)
uv run drone-eval analyse examples/synthetic_deployments/03_coastal-turbine_conflicting

# Context reconstruction only, as JSON (the older entry point)
uv run deployment-context examples/demo_deployment --state /tmp/demo.state.json
```

Exit codes: `0` means every implemented stage ran. `2` means the pipeline
stopped because the context was not ready. `1` means a usage or input error.

## 3. Inputs

| Path | Role |
|---|---|
| `examples/demo_deployment/` | The operator's deployment folder, treated as **read-only**. 15 small files: aircraft and payload records, flight plan, GeoJSON route, site survey, coarse OBJ envelope, forecast, autonomy config, operating limits (including battery energy and reserve), acceptance criteria, telemetry index, CSV log, and an operations brief. Operator-style labels (`aircraft`, `takeoff_mass_kg`, `flight_plan`, `acceptance_criteria`, …) exercise alias normalization. |
| `examples/demo_hypotheses.json` | **Hand-authored** failure hypotheses. It lives outside the deployment folder so it is never ingested as operator evidence. |
| `examples/demo_deployment.json` | Not used by the demo. It is the canonical IR fixture for unit tests. |

The deployment is fictional and must never be used to authorize a flight.

## 4. Expected output

Abbreviated from a real run; paths depend on your checkout.

```text
[1] Context discovery  (✅ implemented)
  files indexed: 15; files opened: 15
  adapters used: binary_metadata x1, csv_summary x1, json x12, text x1
  linked vehicle 'inspectionuav01' across 4 files

[2] Deployment IR reconstruction  (✅ implemented)
  aircraft:   inspection-uav-01 — Example Aerospace Surveyor X (multirotor), 4.2 kg, MTOM 6.0 kg, wind limit 10.0 m/s
  route:      6 waypoints, max 24.0 m (above_ground)
  conditions: wind 6.5 m/s from 170.0 deg, 19.0 C, visibility 10000.0 m
  constraint: usable-energy [energy] = 180.0 Wh
  constraint: landing-reserve [energy] = 0.2 1
  missing/empty optional sections: raw_data, models
  evidence: 132 material facts, each anchored to a source; 0 with competing values
  e.g. /vehicle/mass_kg = 4.2  <- aircraft/approved_current_aircraft.json#/aircraft/takeoff_mass_kg (json, medium confidence)

[3] Context readiness gate (drone_hypothesis_generation_v1)  (✅ implemented)
  status: READY

[4] Failure-mechanism applicability (taxonomy v0.1.0)  (✅ implemented)
  32 mechanisms: 31 applies, 1 unknown, 0 ruled out
  - unknown   deployment_external_actors.dynamic_site.temporary_obstacle (missing /raw_data)

[5] Failure hypotheses  (⚪ not implemented generator; 🟡 hand-authored input)
  loaded 3 hand-authored hypotheses from examples/demo_hypotheses.json
  investigation policy next action: test hyp_roof_clearance at fidelity level 0 (...)

[6] Test selection, execution, and fidelity routing  (✅ implemented; thresholds: 🟡 demo wiring)
  hyp_roof_clearance -> measures collision, minimum_clearance_m
    GAP unproducible_input: site_geometry — geometry.site_model: no registered provider
    routing decision: exhausted after 1 level(s); review required: yes
  hyp_energy_reserve -> measures reserve_breach, remaining_energy_wh
    plan: geometry.route_projection -> dynamics.vehicle_envelope -> weather.wind_field -> weather.atmosphere -> energy.route_demand -> energy.reserve_assessment
    measure remaining_energy_wh = 171.449 ± 1.28 Wh [builtin.momentum-energy@0.1.0]
    threshold remaining_energy_wh gte 36 Wh (from constraint landing-reserve (0.2) x usable-energy (180 Wh))
    boundary remaining_energy_wh: clear — margin 135 exceeds the 2.57 boundary band
    routing decision: accept after 1 level(s); review required: no
  hyp_takeoff_mass -> measures takeoff_rejected, mass_margin_kg
    measure mass_margin_kg = 1.480 kg [builtin.deployment-semantics@0.1.0]
    boundary mass_margin_kg: unquantified — result or an upstream contributor has no declared error
    routing decision: exhausted after 1 level(s); review required: yes

[7] Summary of executed evaluations  (🟡 demo summary — NOT a readiness verdict)
  hyp_roof_clearance: NOT EVALUATED — required capabilities have no registered provider
  hyp_energy_reserve: remaining_energy_wh threshold satisfied (margin +135; clear)
  hyp_takeoff_mass: mass_margin_kg threshold satisfied (margin +1.48; unquantified); router requests review
  mechanisms evaluated: 3 of 31 applicable; 28 remain unexamined

Not implemented yet (the pipeline does not run these):
  ⚪ not implemented: Hypothesis generation — ...
  ⚪ not implemented: Deterministic judges — ...
  ...
Artifacts written:
  .../work/demo_deployment/state.json
  ...
```

Files written to `work/demo_deployment/` (git-ignored):

| File | Contents |
|---|---|
| `state.json` | Persistent context state: candidates, parsed summaries, inspection trace, entity links |
| `context_readiness.json` | Readiness gate report |
| `evidence.json` | The full evidence-backed Deployment IR, with every fact's source anchor |
| `coverage.json` | Applicability of all 32 mechanisms, with predicate evidence |
| `hypotheses.json` | The validated hypothesis contract that was used |
| `routing/<hypothesis>.json` | Plan, node records with digests, measures with lineage, boundary assessments, and justifications |

## 5. What each stage means

1. **Context discovery.** Indexes the folder, searches for each Deployment IR
   field, opens ranked files through bounded deterministic adapters, and links
   shared IDs across files.
2. **Deployment IR reconstruction.** Assembles the canonical, vendor-neutral
   deployment. Every populated value is a `MaterialFact` with its source file,
   JSON Pointer, hash, and confidence.
3. **Context readiness gate.** Decides whether enough trustworthy context
   exists to reason about failures (`ready`, `incomplete`, `uncertain`,
   `conflicting`, or `invalid`). This is **not** deployment readiness.
4. **Applicability.** Evaluates the 32-mechanism drone failure taxonomy
   against the IR. Today a mechanism "applies" whenever its required IR
   sections exist.
5. **Hypotheses.** Specific, falsifiable concerns tied to a mechanism and
   to deployment evidence. The demo loads them from a file because no
   generator exists yet. The investigation policy shows which one it would
   test first.
6. **Test selection and execution.** For each hypothesis, the planner turns
   its observables into a capability graph and binds the cheapest credible
   registered provider. It executes in-process with digests and lineage. The
   fidelity router then checks whether the result is far enough from the
   threshold to accept at that fidelity, or whether it must escalate or
   report `exhausted`.
7. **Summary.** Restates the router's margins. It is explicitly **not** a
   readiness verdict, because no judge or report layer exists.

## What is real and what is not

| Stage | Real code | Stand-in | Missing |
|---|---|---|---|
| Discovery, IR, provenance, readiness gate | ✅ | — | LLM ranking, conflict resolution UX |
| Applicability map | ✅ | — | deployment-specific rule-out profiles |
| Hypotheses | contract validation, investigation policy | `examples/demo_hypotheses.json` (hand-written) | generator |
| Capability selection and planning | ✅ `GraphPlanner` | — | — |
| Models | ✅ rule conversion, momentum-theory energy | — | site-geometry provider, calibrated models, Isaac |
| Execution and fidelity routing | ✅ `execute`, `FidelityRouter` | thresholds from `golden_path.bind_thresholds` | judges |
| Variation and boundary search | — | — | ⚪ entirely |
| Readiness report | — | step 7 demo summary | ⚪ entirely |

## 6. Common failure modes

| Symptom | Cause and fix |
|---|---|
| `drone-eval: command not found` / `Failed to spawn` | Run `uv sync --extra dev` from the repository root. |
| Output differs after you edited code, not files | State is cached in `work/…/state.json` and invalidated only when *folder files* change. Rerun with `--fresh`. |
| `work directory must be outside the read-only deployment folder` | `--work-dir` must not be inside the analysed folder. |
| `ValidationError` loading hypotheses | The contract is strict: unknown keys are rejected, `mechanism_id` must be a taxonomy leaf, and at least one `deployment_evidence` reference is required. |
| A new file in `examples/demo_deployment/` changes the IR or creates conflicts | Every file in the folder is operator evidence. Keep helper files outside it. |
| Readiness shows `conflicting` | Two files disagree. There is no resolution UX yet; fix or remove one source. |
| Docs describe modules you don't have | Your local `main` may be behind `origin/main`; run `git pull`. |

## 7. Reset and re-run

```bash
rm -rf work/demo_deployment
uv run drone-eval analyse examples/demo_deployment --hypotheses examples/demo_hypotheses.json
```

Or keep the directory and pass `--fresh`. The demo never writes into
`examples/`; the Golden Path test asserts this.

## Keeping the demo current

`tests/test_golden_path.py` asserts the key values shown above. If a change
alters them, update this file, `CURRENT_STATE.md`, and the test in the same
change.
