# Repository instructions

Read this file fully before changing the repository. This is the mandatory,
always-on context for Zed and Codex agents.

## Context hierarchy

Use these sources in order:

1. `AGENTS.md` — mandatory persistent instructions.
2. [`docs/PRODUCT.md`](docs/PRODUCT.md) — canonical product truth.
3. [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) — what is actually
   implemented, partial, planned, or broken today.
4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — intended architecture and,
   separately, the current implementation.
5. [`docs/DECISIONS.md`](docs/DECISIONS.md) — rationale for major choices.
6. [`docs/DEMO.md`](docs/DEMO.md) and [`docs/TESTING.md`](docs/TESTING.md) —
   how to run the Golden Path and each test layer.
7. Linear or GitHub — current task-specific context.
8. Code — implementation truth.

## Product boundary

This is a **DRONES/UAVs ONLY** product. Do not generalize requirements,
integrations, schemas, ontologies, architecture, or infrastructure solely for
ground robots, autonomous cars, humanoids, manipulators, marine robots, or any
other modality. Expansion is deferred until the drone product is complete,
validated, and high quality end to end.

We are building autonomous pre-deployment verification for known-working
drones. Assume the aircraft and autonomy stack already work well. The product
must answer:

> Is this known-working drone ready for this specific deployment across the
> plausible conditions it may encounter?

The primary UX is not a prompt asking which test to run. The system should
reconstruct the deployment, discover plausible failure hypotheses, select
models and tools, test at minimum credible fidelity, escalate uncertain cases
to Isaac Sim or Isaac Lab, search failure boundaries, and return an
evidence-backed readiness report.

## Architectural directives

- Be agentic at the edges and deterministic in the core.
- Keep canonical semantics separate from pluggable implementations.
- Keep Deployment IR and Scenario IR model- and simulator-agnostic.
- Use LLMs for context discovery, hypotheses, planning, capability selection,
  and summaries. Use deterministic parsers, models, simulators, and judges to
  establish results.
- Start with the cheapest credible model; escalate fidelity only when the
  failure mechanism or uncertainty requires it.
- Use Isaac Sim and Isaac Lab as the default high-fidelity backend. Add a
  specialized simulator only when an important drone failure mode cannot be
  covered economically.
- Treat provenance and uncertainty as first-class.
- Never let an LLM generate arbitrary simulator code in the core execution path.
- Treat scene acquisition as an input pipeline, not the product. Accept existing
  meshes, point clouds, CAD, and GIS first; reconstruct historical imagery or
  video later.

## Before starting work

1. Read `AGENTS.md` fully.
2. Read `docs/PRODUCT.md`.
3. Read `docs/CURRENT_STATE.md` and `docs/ARCHITECTURE.md`. Make sure local
   `main` matches `origin/main` first (`git pull`).
4. Read the relevant Linear or GitHub issue before implementing.
5. Inspect the repository before proposing architecture changes.
6. Preserve drone-only scope.
7. Flag conflicts with documented architecture or decisions before proceeding.
8. Update `docs/DECISIONS.md` when a meaningful architectural decision changes.

## Definition of Done for agent work

No Linear or GitHub implementation issue is complete until the agent reports
all of the following. Put the report in the PR description and the final
message to the user, and link it from the Linear comment. A contract or
library function with unit tests is not a working pipeline stage; say which
one was delivered.

### What changed
A concise explanation.

### Why it exists
How it supports the drone deployment-verification product.

### Where it fits
Which part of the architecture it belongs to (name the stage in
`docs/ARCHITECTURE.md` → Current implementation).

### How to run it
Exact command(s).

### How to test it
Exact command(s) and expected behavior, including the test layer
(`-m component`, `-m integration`, `-m golden`).

### What I should see
Expected output, UI state, files, logs, or traces.

### Demo impact
Whether and how the Golden Path (`uv run drone-eval analyse
examples/demo_deployment --hypotheses examples/demo_hypotheses.json`)
changed: a stage that became real, a stand-in that was removed, or new
output. If it did not change, say why.

### Current limitations
Known missing behavior, mocks, stubs, assumptions, or unsupported cases.

### Files changed
Important files only.

### Documentation updated
Which of these were updated, and why any relevant one was not:
- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE.md`
- `docs/DEMO.md`
- `docs/TESTING.md`
- `docs/DECISIONS.md`

If a feature cannot be demonstrated or tested, the agent must explain why
before declaring the work complete. Never mark a component ✅ in
`CURRENT_STATE.md` unless a test or the Golden Path exercises it. Use
`docs/MILESTONE_REVIEW.md` at the end of each milestone.

## Linear

Use only the external Linear MCP tools in the `mcp__linear__.*` namespace for all Linear work. Do not use bundled Codex Apps or Computer Use fallback for Linear.

## Git

One Linear issue, one branch, one PR.

Commit once, when the issue's acceptance criteria are met and the tests pass. Do not commit after each file, and do not commit work that fails tests.

Stage only files this issue changed. One-line message: "LIN-123: <what changed>".

Immediately after that commit:
- git push -u origin HEAD
- gh pr create, not draft, with the issue id in the title and a link to the Linear issue in the body
- comment the PR URL on the Linear issue and move it to In Review

Never push to main, force-push, or amend.

After the PR is open, enable auto-merge. Do not merge unless GitHub checks are green. If checks fail, stop.

Turn on auto-merge in the repo, and require the test check in branch protection. Then the agent can finish the ticket without you, and a red test still blocks main.

Do not add "merge everything" with no checks. That is faster for an hour and slower for the rest of the MVP.
