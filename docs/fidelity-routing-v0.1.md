# Fidelity routing policy v0.1

The fidelity router chooses the cheapest credible provider for each capability
a hypothesis needs, escalates only when the evidence requires it, and records
why. It sits between the capability graph planner and deterministic judges: it
reads decision thresholds to measure margins, but it never issues pass or fail
verdicts.

## Inputs the policy considers

| Factor | How it is used |
| --- | --- |
| causal mechanism | mechanism floors set minimum fidelity per capability |
| required outputs | goal measures determine which capabilities are routed |
| validity region | providers outside validity are unusable; unconfirmed validity escalates |
| expected uncertainty | declared or emitted errors define the boundary band |
| distance from boundary | margin within `boundary_factor` × error escalates |
| computational cost | among eligible providers: fidelity, validity, cost, runtime |
| closed-loop or sensor realism | closed-loop composites and appearance-driven mechanisms start at high-fidelity simulation |

## When each fidelity is sufficient

- **Analytical or rule-based** evaluation is sufficient when the mechanism is
  a static or integral quantity — mass margin, route energy, timing, declared
  rules — the provider is inside its validity region, every contributor to the
  measure has a declared error, and the margin to the decision threshold
  exceeds the boundary band.
- **Geometric or physics** providers suffice without rendering when the outcome
  depends on shape, distance, forces, or link geometry but not sensor
  appearance: clearance, containment, line of sight, tracking response, and
  battery physics.
- **High-fidelity simulation** (Isaac Sim or Isaac Lab by default) is required
  from the start when the mechanism needs closed-loop interaction between
  autonomy, dynamics, and sensing (closed-loop composite capabilities) or
  rendered sensor appearance (visibility, feature-poor localization, surface
  material, occlusion and contamination). It is also the escalation target
  when a lower-fidelity result remains near the boundary, unquantified, or of
  unconfirmed validity.

## Routing loop

`FidelityRouter.investigate(goal, context, thresholds, initial)`:

1. derives mechanism floors from the policy;
2. plans the goal with a selector that picks, per capability, the lowest
   fidelity at or above its floor, preferring confirmed validity, then cost
   and runtime, and records a justification naming bypassed providers;
3. executes the plan and assesses each decision measure as `clear`,
   `near_boundary`, `unquantified`, `validity_unconfirmed`, or `missing`;
4. accepts when every measure is clear; otherwise raises the producing
   capability's floor to the next available fidelity class and repeats; and
5. stops as `exhausted` when no higher-fidelity provider exists.

Every `RoutingStep` stores floors, bound providers, selection and decision
justifications, assessments, and the full execution record, so the same
hypothesis can be traced through each fidelity level it was tested at.

## Disagreement between fidelity levels

Consecutive levels are compared for every shared numeric measure. When the
difference exceeds the sum of their error widths, a `Disagreement` is recorded
and the outcome `requires_review`. The higher-fidelity result is not assumed
correct: disagreement is evidence that one model's trust region or error model
is wrong, which trust tracking must resolve before a high-confidence finding.
