# Golden Path demo

One command starts a persisted agent session on one fictional drone
deployment. It reconstructs context, displays anchored facts and hypotheses,
executes the available deterministic evaluations, and states exactly what the
evidence does and does not establish. What is real and what is not is summarized in the
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

No GPU, network access, Isaac installation, or API key is needed. Recorded
responses exercise the LLM contracts without making a hosted call.

## 2. Run it

```bash
uv run drone-eval agent examples/demo_deployment
```

Useful variants:

```bash
# Persist answers and reject a proposed hypothesis before investigation
uv run drone-eval agent examples/demo_deployment --answers answers.json

# Run a non-demo folder with recorded LLM responses
uv run drone-eval agent my_deployment --replay session_replay.json

# Manual hosted verification (uses your explicitly supplied key)
ANTHROPIC_API_KEY=... uv run drone-eval agent examples/demo_deployment --live --llm-policy hosted-policy.json --fresh

# A folder with contradictory evidence: stops at the readiness gate (exit code 2)
uv run drone-eval analyse examples/synthetic_deployments/03_coastal-turbine_conflicting

# Context reconstruction only, as JSON (the older entry point)
uv run deployment-context examples/demo_deployment --state /tmp/demo.state.json
```

Hosted mode requires an explicit per-deployment policy such as
`{"allow_hosted_llm":true,"redaction_patterns":[]}`. With no policy, `--live`
runs the deterministic context/applicability stages and records that no bytes
were sent. Replay remains local and does not require hosted-call permission.

Exit codes: `0` means every implemented stage ran. `2` means the pipeline
stopped because the context was not ready. `1` means a usage or input error.

## 3. Inputs

| Path | Role |
|---|---|
| `examples/demo_deployment/` | The operator's deployment folder, treated as **read-only**. It includes aircraft and payload records, flight plan, route, site survey, coarse geometry, forecast, autonomy config, operating limits, acceptance criteria, telemetry, and operator documents. |
| `examples/replays/demo_agent_replay.json` | Recorded typed LLM responses for document extraction, hypothesis generation, and summary writing in CI. |
| `examples/demo_deployment/operations/battery_spec.md` | Document-only battery fact. The replay extraction must quote and anchor line 3 exactly. |
| `examples/demo_deployment.json` | Not used by the demo. It is the canonical IR fixture for unit tests. |

The deployment is fictional and must never be used to authorize a flight.

## 4. Expected output

Abbreviated from a real run; paths depend on your checkout.

```text
Drone deployment verification — Agent session
[context] Examined the deployment files.
[facts] Extracted 127 anchored material facts.
[document] Verified document fact 180 from operations/battery_spec.md#3-3.
[hypothesis] hyp_energy_reserve: The 6.5 m/s forecast wind and 4.2 kg takeoff mass raise route power demand. -> ...
[hypothesis] hyp_takeoff_mass: The configured drone mass is 4.2 kg against a 6.0 kg approved maximum. -> ...
[hypothesis] hyp_roof_clearance: The inspection pass is planned at 24.0 m over a site referenced at 12.0 m. -> ...
[evaluation] hyp_energy_reserve: remaining_energy_wh threshold satisfied (margin +135; clear)
[evaluation] hyp_takeoff_mass: mass_margin_kg threshold satisfied (margin +1.48; unquantified); router requests review
[evaluation] hyp_roof_clearance: NOT EVALUATED — required capabilities have no registered provider

NOT A READINESS VERDICT
- hyp_energy_reserve: remaining_energy_wh threshold satisfied (margin +135; clear)
- hyp_takeoff_mass: mass_margin_kg threshold satisfied (margin +1.48; unquantified); router requests review
- hyp_roof_clearance: NOT EVALUATED — required capabilities have no registered provider
- limitation: Results are limited to executed providers and nominal conditions.

```

Files written to `work/demo_deployment/` (git-ignored):

| File | Contents |
|---|---|
| `state.json` | Persistent context state: candidates, parsed summaries, inspection trace, entity links |
| `context_readiness.json` | Readiness gate report |
| `evidence.json` | The full evidence-backed Deployment IR, with every fact's source anchor |
| `coverage.json` | Applicability of all 32 mechanisms, with predicate evidence |
| `generated_hypotheses.json` | Contract-validated generator output after optional accept/reject review |
| `knowledge_bundle.json` | Provenance-qualified folder, curated platform, and model-prompt knowledge consumed by generation |
| `hypothesis_generation_audit.json` | Per-mechanism covered/missing/unmeasurable accounting after deterministic grounding checks |
| `agent_session.json` | Persistent operator trace, questions, and evidence-bounded summary |
| `llm_ledger.json` | Every replay/live LLM call, input references, context trace links, validation outcome, token usage, latency, and cost |
| `tool_ledger.json` | Every bounded deterministic agent-tool call with arguments, timestamp, and result digest |
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
   deployment evidence. The demo uses an offline replay proposal set, which
   can be accepted or rejected through an answers file before investigation.
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
| Hypotheses | typed generator, validation, review, and investigation policy | recorded provider response in CI | hosted run is opt-in |
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
uv run drone-eval agent examples/demo_deployment
```

Or keep the directory and pass `--fresh`. The demo never writes into
`examples/`; the Golden Path test asserts this.

## Keeping the demo current

`tests/test_golden_path.py` asserts the key values shown above. If a change
alters them, update this file, `CURRENT_STATE.md`, and the test in the same
change.
