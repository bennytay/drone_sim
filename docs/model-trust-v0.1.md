# Model validation and trust regions v0.1

A capability match says a provider *can* compute a measure. Trust says whether
its result is supported by validation evidence at this operating point, for
this model version, and for this customer or deployment. The `TrustLedger`
keeps that evidence outside provider manifests so the platform, not the
provider, decides how much a result can support.

## What is recorded

Each `ModelTrustRecord` belongs to exactly one `model_id@version` and holds:

- **validation datasets** — the operating region covered, sample count, scope,
  and whether the platform reproduced the comparison (`verified`, which
  requires a SHA-256-pinned artifact) or only received an attestation;
- **residual distributions** — running observed-minus-predicted statistics per
  measure and scope (count, bias, variance, maximum), mergeable across scopes;
- **unsupported regions** — explicit extrapolation regions where the model must
  not be used;
- **deployment feedback** — every observed outcome with its operating context
  and source; and
- **drift flags** — measures whose latest residual departed from history.

Provider-declared `trust_regions` can be imported with
`seed_from_manifest`; they enter as unverified attestations.

## Trust levels and required evidence

| Level | Meaning | Maximum finding confidence |
| --- | --- | --- |
| `validated` | an applicable dataset covers the operating point | `high` only with verified data, ≥ 30 residual samples for the measure, and no drift; otherwise `medium` |
| `extrapolated` | inside claimed validity but outside every applicable validated region | `low` |
| `unvalidated` | no evidence for this version (evidence for other versions is named, never inherited) | `low` |
| `unsupported` | outside claimed validity or inside a declared unsupported region | `unknown`; cannot support findings |

The empirical error bound is |bias| + 2σ of the pooled residuals. When it is
wider than a provider's declared error, routing uses the empirical bound.

## Scope

Evidence is global, customer-scoped, or deployment-scoped. Global evidence
applies everywhere; customer evidence applies to that customer's deployments
(deployment identifiers prefixed `<customer>/`); deployment evidence applies
only to that deployment. Customer-private learning therefore never leaks into
another customer's assessment.

## Deployment feedback

`record_outcome` folds a real outcome into the residuals for its scope. Once a
scope has 10 outcomes for a measure, their bounding operating region becomes a
feedback validation dataset, so trust regions grow only where real outcomes
exist. A residual more than 4σ from history flags drift, capping confidence at
`medium` until reviewed. Feedback datasets are unverified until the platform
reproduces them from pinned logs.

## Effect on model selection

When `FidelityRouter` is given a ledger:

- providers `unsupported` at the operating point are never selected;
- among eligible providers at the same fidelity, better trust wins over lower
  cost or runtime, and the selection justification names the less-trusted
  alternatives it passed over;
- a result from a provider that is not `validated` is assessed `untrusted` and
  escalates to a higher-fidelity provider; and
- each assessment records the trust level and maximum confidence, which the
  readiness report must carry with the finding.

## Reporting findings outside validated regions

`TrustAssessment.report_note()` states the model, trust level, the reason
(for example the variables outside the validated region), and the confidence
cap. A finding from an extrapolated or unvalidated model may be reported, but
only with that qualification and never above `low` confidence.
