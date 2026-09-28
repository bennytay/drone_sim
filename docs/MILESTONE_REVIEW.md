# Milestone review checklist

Use this at the end of every Linear milestone, or before calling a batch of
issues "done". Copy it into the milestone review comment and tick each item
with evidence: a command, output, or link. An unchecked item needs a written
reason.

## Runs

- [ ] `git pull` done; review is against current `origin/main` (record the commit).
- [ ] `uv sync --extra dev` succeeds on a clean checkout.
- [ ] The Golden Path runs:
      `uv run drone-eval analyse examples/demo_deployment --hypotheses examples/demo_hypotheses.json --fresh`
- [ ] Its output still matches `docs/DEMO.md`, or `DEMO.md` was updated in the same change.
- [ ] Demo reset steps in `docs/DEMO.md` still work.

## Tests

- [ ] `uv run pytest -m component` passes.
- [ ] `uv run pytest -m integration` passes.
- [ ] `uv run pytest -m golden` passes.
- [ ] CI `test` check is green on the merged PRs.
- [ ] New behavior has a test in the right layer (`tests/conftest.py`).

## Documentation reflects reality

- [ ] `docs/CURRENT_STATE.md` status table is updated for every component the milestone touched.
- [ ] `docs/ARCHITECTURE.md` "Current implementation" diagram is updated; "Intended architecture" status markers match.
- [ ] No planned component is described as implemented anywhere (README, docs, PR descriptions, Linear).
- [ ] Every ✅ is backed by a test or the Golden Path.
- [ ] Known limitations, stubs, and demo stand-ins are listed in `CURRENT_STATE.md`.
- [ ] Linear "Done" issues match code on `main` (a contract with unit tests is not a working pipeline stage; say which it is).
- [ ] Important architectural decisions are recorded in `docs/DECISIONS.md`.
- [ ] Drone-only scope is preserved.

## Explainability

- [ ] I can explain what changed in this milestone without reading source code.
- [ ] I can say how the Golden Path moved: which stage became real, or which stand-in was removed.
- [ ] The two-minute explanation in `docs/PRODUCT.md` is still accurate.

## Record

| Field | Value |
|---|---|
| Milestone | |
| Commit reviewed | |
| Golden Path furthest real stage | |
| Stand-ins still in use | |
| New known defects | |
| Reviewer / date | |
