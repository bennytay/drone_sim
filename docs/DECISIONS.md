# Architectural decisions

This lightweight decision log records settled choices. Update it when a
meaningful architectural decision changes; do not rewrite history silently.

## ADR-001: Drone-only product boundary

**Decision:** Build exclusively for drones and UAVs until the product is
complete, validated, and high quality end to end.

**Rationale:** Drone deployments have specific flight, weather, airspace,
energy, payload, perception, and site risks. Generalizing early would increase
ontology and infrastructure cost before the core product is proven.

**Revisit when:** The drone product works end to end for real deployments and a
separate expansion phase has explicit evidence, scope, and ownership.

## ADR-002: Assume a known-working drone

**Decision:** Verify deployment-specific readiness; do not solve basic vehicle
or autonomy development.

**Rationale:** The valuable last-mile question is whether a functioning system
is ready for a particular site, mission, and range of plausible conditions.
This assumption keeps hypotheses and evaluation focused.

**Revisit when:** Deployment evidence shows that separating base-system defects
from deployment mismatch is impossible or commercially undesirable.

## ADR-003: Isaac is the default high-fidelity backend

**Decision:** Use Isaac Sim and Isaac Lab as the primary general high-fidelity
execution backend.

**Rationale:** They provide a strong path for physics, sensors, scalable
variation, and closed-loop drone autonomy while allowing one integration to
cover multiple high-fidelity investigations.

**Revisit when:** A material drone failure family cannot be represented
credibly or economically, or another backend offers clearly superior validated
coverage for the product's dominant workload.

## ADR-004: CARLA is not the core or default backend

**Decision:** Do not make CARLA the platform's core or default simulator.

**Rationale:** CARLA is optimized around autonomous-road-vehicle scenarios.
Adopting its semantics as the product core would distort a drone-only model and
duplicate the role assigned to Isaac.

**Revisit when:** A high-value drone deployment failure depends on a CARLA
capability that cannot be supplied more economically through the default stack;
in that case, consider a specialized adapter rather than a core migration.

## ADR-005: Model- and simulator-agnostic IRs

**Decision:** Keep Deployment IR and Scenario IR independent of source vendors,
models, and simulators.

**Rationale:** Canonical semantics let evidence, hypotheses, tests, and results
survive implementation changes. Typed adapters isolate DJI, PX4, Isaac, model,
and file-format details.

**Revisit when:** A required concept cannot be expressed without losing
material meaning after multiple concrete adapter attempts. Extend canonical
semantics for the concept, not for one vendor API.

## ADR-006: Automatic hypothesis-driven testing

**Decision:** The primary workflow autonomously discovers failure hypotheses
and selects tests instead of asking the operator which test to run.

**Rationale:** Operators know deployments, not necessarily simulation or model
selection. The product's value is converting messy context into defensible,
appropriately scoped investigation.

**Revisit when:** User research shows a specific regulated workflow requires
manual approval or selection. Add control points without turning manual test
authoring into the default experience.

## ADR-007: Agentic at the edges, deterministic in the core

**Decision:** Use agents for discovery, hypothesis formation, planning,
selection, and explanation. Use deterministic parsers, models, simulators, and
judges for facts and results.

**Rationale:** Agents handle open-ended context efficiently, while deterministic
execution provides repeatability, observability, validation, and trust. An LLM
must not generate arbitrary simulator code in the core path.

**Revisit when:** A learned or agentic component demonstrates validated,
bounded behavior for a core function and preserves reproducibility, provenance,
and an independent evaluation path.

## ADR-008: Scene realism only where causally required

**Decision:** Add scene detail only when it can affect the failure mechanism
under test. Treat scene acquisition as an input pipeline, not the product.

**Rationale:** Maximum visual or physical realism is expensive and often
irrelevant. Failure-mode-driven fidelity reduces acquisition, preparation, and
compute cost while keeping tests credible.

**Revisit when:** Evaluation evidence shows missing scene detail materially
changes decisions across important drone failure modes or richer acquisition
becomes cheap enough to alter the trade-off.

## ADR-009: Carry provenance in a versioned evidence envelope

**Decision:** Keep Deployment IR's canonical values free of ingestion-specific
wrappers and carry them in an `EvidenceBackedDeployment` envelope. Require one
evidence record for every populated scalar field, addressed by JSON Pointer.
Each record keeps the selected and competing candidates, exact source anchors,
extraction method, qualitative uncertainty, value origin, assumptions, and
derivation inputs.

**Rationale:** Wrapping every value would make canonical drone semantics hard
to consume and would couple all evaluators to ingestion mechanics. A validated
envelope preserves a complete, portable chain while allowing deterministic
models and simulators to consume ordinary typed values. Ordinal confidence with
a written basis avoids implying that uncalibrated scores are probabilities.

**Revisit when:** Field-level wrappers materially simplify multiple downstream
implementations, or evidence shows JSON Pointer identity is unstable across
required schema migrations. Any replacement must retain complete coverage,
conflicts, assumptions, and derivation lineage.

## ADR-010: Evaluation-specific deterministic readiness thresholds

**Decision:** Assess context completeness against a typed evaluation profile
whose dependencies and minimum confidence are explicit. Return one of `ready`,
`incomplete`, `uncertain`, `conflicting`, or `invalid`. Do not automatically
resolve contradictory values: require an auditable resolution method, selected
candidate, complete rejected-candidate set, and rationale. Source adapters must
convert common non-SI aviation units into canonical Deployment IR units.

**Rationale:** A deployment can be complete enough for hypothesis generation
but not for a wind, energy, geometry, or perception evaluation. One universal
completeness flag would either block useful investigation or admit unsupported
tests. Explicit profiles make the stopping condition reproducible, while
structured findings tell the context agent exactly what evidence to seek next.

**Revisit when:** Real drone evaluations show stable dependency families that
should become a versioned registry, or calibrated uncertainty supports more
precise thresholds without creating false confidence.
