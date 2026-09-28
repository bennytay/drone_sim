# Milestone review checklist

Use this at the end of every Linear milestone, or before calling a batch of
issues "done". Copy it into the milestone review comment and tick each item
with evidence: a command, output, or link. An unchecked item needs a written
reason.

## Runs

- [x] `git pull` done; final review started from `origin/main` at `ccce31f`.
- [x] `uv sync --extra dev` succeeds.
- [x] The Golden Path runs: `uv run drone-eval agent examples/demo_deployment --fresh`.
- [x] Its output matches the updated `docs/DEMO.md`.
- [x] Demo reset steps in `docs/DEMO.md` work.

## Tests

- [x] `uv run pytest -m component` passes.
- [x] `uv run pytest -m integration` passes.
- [x] `uv run pytest -m golden` passes.
- [x] CI `test` checks are green on merged BEN-64 through BEN-79 PRs, including BEN-76 PR #51 and BEN-77 PR #52.
- [x] New behavior is exercised by the Golden layer (`test_agent_session.py`, `test_golden_path.py`).

## Documentation reflects reality

- [x] `docs/CURRENT_STATE.md` status table covers the milestone components.
- [x] `docs/ARCHITECTURE.md` current implementation is updated.
- [x] Planned components remain labelled partial or missing.
- [x] Every new completion claim is exercised by replay tests or the Golden Path.
- [x] Known limitations and the remaining threshold stand-in are listed.
- [x] Linear marks every BEN-64 through BEN-79 issue Done, and each implementation PR is merged.
- [x] ADR-023 records replay generation and the remaining judge stand-in.
- [x] Drone-only scope is preserved.

## Explainability

- [x] The milestone is summarized in `CURRENT_STATE.md` and `DEMO.md`.
- [x] The hand-authored hypothesis input was removed; replay/live generation is now in the Golden Path.
- [x] The two-minute explanation in `docs/PRODUCT.md` remains accurate.

## Record

| Field | Value |
|---|---|
| Milestone | Agentic LLM Layer: Ingestion & Hypotheses |
| Commit reviewed | `ccce31f` |
| Golden Path furthest real stage | Replayed LLM extraction → generated hypothesis → deterministic evaluation → investigation stop → bounded summary |
| Stand-ins still in use | Threshold binding until BEN-37; recorded LLM responses in CI |
| New known defects | None found; known limitations remain the labelled threshold binding, no deterministic judges, no boundary search, and no Isaac adapter |
| Reviewer / date | Codex / 2026-09-28 |
