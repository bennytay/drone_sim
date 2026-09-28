# Failure hypothesis contract v0.1

`FailureHypothesis` turns a drone deployment concern into a planner-ready,
falsifiable object. It requires a taxonomy mechanism, affected success target,
causal variables and path, deployment-evidence support, uncertainty and its
basis, materiality, candidate deterministic test modalities, and qualitative
confirmation and falsification observations.

The contract deliberately contains no proposed numerical pass/fail threshold.
Only a registered model and deterministic judge may bind an observable to a
threshold. This keeps agent-generated discovery useful without allowing prose
to establish readiness.

Hypotheses must cite deployment evidence even when taxonomy or external
knowledge motivates their discovery. Duplicate identity is deterministic:
mechanism, affected target, and variable names. Overlapping active proposals
are rejected; `merge_duplicates` preserves duplicates as merged records with a
link to the canonical hypothesis.
