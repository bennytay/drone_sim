# Repository instructions

Read this file fully before changing the repository. This is the mandatory,
always-on context for Zed and Codex agents.

## Context hierarchy

Use these sources in order:

1. `AGENTS.md` — mandatory persistent instructions.
2. [`docs/PRODUCT.md`](docs/PRODUCT.md) — canonical product truth.
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — canonical current system model.
4. [`docs/DECISIONS.md`](docs/DECISIONS.md) — rationale for major choices.
5. Linear or GitHub — current task-specific context.
6. Code — implementation truth.

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
3. Read `docs/ARCHITECTURE.md`.
4. Read the relevant Linear or GitHub issue before implementing.
5. Inspect the repository before proposing architecture changes.
6. Preserve drone-only scope.
7. Flag conflicts with documented architecture or decisions before proceeding.
8. Update `docs/DECISIONS.md` when a meaningful architectural decision changes.

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
