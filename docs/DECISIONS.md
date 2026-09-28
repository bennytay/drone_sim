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

## ADR-011: Bounded deterministic source-adapter registry

**Decision:** Dispatch deployment artifacts through a suffix-registered,
deterministic adapter interface returning a common `ParsedSource`. Parse small
structured files directly, stream large tabular telemetry into summaries,
bound extracted document text, and return metadata rather than raw bytes for
binary drone logs, site models, point clouds, images, and video.

**Rationale:** Agents need searchable evidence summaries, not raw multi-gigabyte
logs or meshes. A single bounded result contract keeps parsing reproducible,
records source hashes and truncation, and allows format-specific decoders to be
added without putting vendor semantics into Deployment IR or using an LLM as a
parser.

**Revisit when:** A material drone evaluation requires random access to a
specific time-series or geometry payload. Add a typed selective-query method or
specialized deterministic decoder while retaining bounded agent-facing output.

## ADR-012: Dependency-driven reconstruction with deferred clarification

**Decision:** Reconstruct messy drone deployment folders using reusable
dependency templates, deterministic aliases, ranked evidence, cached parsed
summaries, and identifier-based entity links. Prefer sources marked current,
approved, final, release, or signed over stale/archive signals, but preserve all
competing values for conflict validation. Ask the operator only after the
bounded evidence search is exhausted.

**Rationale:** Operator folders rarely follow one naming convention. Encoding a
curated layout would silently miss evidence, while indiscriminate reading would
waste context and make behavior irreproducible. Templates expose why a file was
sought; deterministic normalization preserves provenance; cache invalidation
supports repeated analysis; and targeted clarification keeps missing evidence
visible without making manual data entry the primary UX.

**Revisit when:** Real deployment corpora justify learned relevance or entity
matching. Learned ranking may augment these deterministic records, but cannot
replace traceable source selection, conflict preservation, or stopping rules.

## ADR-013: Versioned mechanism taxonomy separate from applicability

**Decision:** Represent last-mile drone failure knowledge as a versioned,
hierarchical catalog with stable mechanism IDs. Every testable leaf declares
causal variables, observable outcomes, and relevant Deployment IR paths. Keep
the catalog separate from deployment-specific applicability and coverage state,
and explicitly exclude upstream development defects without a deployment
trigger.

**Rationale:** A stable catalog gives autonomous discovery a reviewable coverage
surface without turning every deployment into a generic checklist. Separating
knowledge from applicability lets evidence rule branches out while preserving
the distinction between irrelevant and unexamined risks. Keeping thresholds out
of the taxonomy prevents proposed mechanisms from becoming unsupported pass or
fail claims.

**Revisit when:** Representative deployment audits expose missing domains or
show that leaf identity cannot survive normal taxonomy evolution. Extend or
version the catalog without silently reinterpreting historical audit records.

## ADR-014: Three-valued applicability and explicit residual risk

**Decision:** Determine taxonomy applicability with deterministic,
evidence-recorded predicates that yield `applies`, `ruled_out`, or `unknown`.
Map these to coverage states without treating unavailable context as an
irrelevant failure branch. Preserve unexamined, tested, uncertain, escalated,
and ruled-out coverage separately, and always retain residual unknown-risk
records.

**Rationale:** A binary relevant/not-relevant result conceals the difference
between evidence disproving a mechanism and insufficient context to judge it.
The three-valued result keeps the next evidence request or investigation
auditable. Residual risk prevents broad taxonomy accounting from being
misreported as an exhaustive safety assurance.

**Revisit when:** Calibrated evidence confidence can safely supplement the
three-valued decision while preserving an explicit unknown state and complete
predicate provenance.

## ADR-015: Falsifiable hypotheses without agent-authored verdict thresholds

**Decision:** Require each failure hypothesis to reference a taxonomy leaf and
deployment evidence, state causal variables and an expected path, name an
affected target, preserve uncertainty and materiality, and provide qualitative
conditions that could confirm or falsify it. Do not permit the hypothesis
contract to establish numeric pass/fail thresholds.

**Rationale:** This makes agent-generated concerns actionable by a test planner
while preserving the deterministic boundary for readiness verdicts. A stable
duplicate key and explicit merged records retain source provenance rather than
silently discarding overlapping proposals.

**Revisit when:** A validated capability registry can supply typed quantitative
threshold references without letting free-form agent output define them.

## ADR-016: Capabilities are tool-independent causal transformations

**Decision:** Define a versioned capability ontology in which each capability
is one causal transformation with typed canonical inputs, outputs, and named
measures. Keep fidelity, cost, runtime, and implementation on registered
providers. Represent tightly coupled feedback as closed-loop composite
capabilities provided as a unit. Bind every failure-taxonomy leaf to a minimum
capability set and validate that binding for dataflow closure and outcome
coverage. Reject vendor or simulator names in the ontology.

**Rationale:** The planner must reason about what a hypothesis needs, not which
product computes it. Capabilities at the granularity of one causal
transformation let multiple fidelity levels satisfy the same need, keep
dependency graphs acyclic, and let new providers become available without
changing hypothesis semantics.

**Revisit when:** Real providers routinely need to split or merge capabilities
to be registered, or closed-loop composites become too coarse to route
fidelity economically. Version the ontology rather than reinterpreting existing
bindings.

## ADR-017: Providers register declarative manifests against the ontology

**Decision:** Every model or tool registers a versioned `ToolManifest` that
binds it to ontology capabilities with canonical ports and measures, declares
airframes, conditional provisions, claimed validity region, fidelity, cost,
runtime, execution mode, per-measure errors, empirical trust regions,
disclosure, and reproducibility. Registration rejects non-canonical contracts.
Opaque providers must run behind a service boundary and supply error and
validation evidence. Region membership is three-valued.

**Rationale:** The planner can only compose and compare providers it
understands from metadata. Declaring validity separately from validated trust
prevents extrapolation from masquerading as evidence, and requiring
contract-level evidence for opaque models lets customers keep internals private
without weakening credibility checks.

**Revisit when:** Real providers need richer validity descriptions than
per-variable intervals, airframes, and tags, or runtime and cost must be
estimated per scenario rather than declared per provider.

## ADR-018: External knowledge enriches but does not override deployment evidence

**Decision:** Record source kind, locator, retrieval time, publication time
where available, hash, summary, and allowed use for knowledge enrichment. Let
broad engineering, platform, and model knowledge prompt hypotheses only;
customer deployment evidence takes precedence over fact-eligible external
claims.

**Rationale:** Recency and provenance make external context reviewable while
preventing generic knowledge from silently replacing customer-specific facts.

## ADR-019: One canonical payload type per data kind with enforced conventions

**Decision:** Map every ontology data kind to one typed payload. Require SI
units, a shared local ENU frame per test, UTC-epoch-relative time,
meteorological wind direction, and SHA-256-pinned references for large series
and assets. Validate ports, frames, and measures in the adapter base class.
Treat Deployment IR semantic conversion as a registered provider, and confine
model-specific adaptation to each adapter.

**Rationale:** Composition without bespoke integration requires that any
producer of a kind can feed any consumer of that kind. Enforcing conventions at
the boundary turns silent unit, frame, or datum mismatches into immediate
errors, and pinned references keep large drone logs and meshes out of the
planner while preserving reproducibility.

**Revisit when:** Site-scale tangent-plane frames become inadequate for long
BVLOS routes, or a material evaluation needs spatially varying fields that
cannot be represented by referenced grids.

## ADR-020: Deterministic backward-chaining capability graphs

**Decision:** Agents choose evaluation goals; a deterministic planner expands
them backwards from measures to capabilities, binds providers through a
pluggable selector, and expands dependencies from the chosen provider's ports.
Plans are acyclic; closed-loop coupling is represented only inside composite
capabilities provided as a unit. Unsatisfiable elements are explicit gaps.
Execution records digests, lineage, failures, and uncertainty contributors
without numerically combining errors outside a registered capability.

**Rationale:** Deterministic search makes test paths reproducible and
auditable, while provider-driven expansion avoids unnecessary upstream work.
Explicit gaps and unquantified-contributor flags prevent silent coverage loss
and unsupported confidence.

**Revisit when:** Goals routinely need multiple providers for the same
capability in one plan, or search over alternative providers must optimize
global cost rather than choosing greedily per capability.

## ADR-021: Margin-driven, justified fidelity escalation

**Decision:** Route each capability to the lowest fidelity allowed by
mechanism floors, preferring confirmed validity, then cost. Escalate the
producing capability one fidelity class when a decision measure lies within
`boundary_factor` times its error of the threshold, lacks quantified
uncertainty, or comes from a provider whose validity cannot be confirmed.
Closed-loop composites and appearance-driven perception mechanisms start at
high-fidelity simulation. Record justifications for every selection and
escalation, and flag cross-level disagreement for review instead of trusting
the higher-fidelity result by default.

**Rationale:** Most drone deployment questions are settled by cheap models
when the margin is large; spending simulation budget only near decision
boundaries or where mechanisms demand feedback or rendering keeps
investigations economical while every escalation remains explainable.

**Revisit when:** Calibrated error models support probabilistic stopping rules,
or escalation of upstream capabilities (not only the measure's producer) is
needed to resolve boundary cases.

## ADR-022: Platform-held, version-specific model trust

**Decision:** Keep validation evidence in a trust ledger separate from provider
manifests. Trust is per model version and per global, customer, or deployment
scope, never inherited across versions. High-confidence findings require
verified (pinned, platform-reproduced) validation coverage, sufficient residual
samples for the measure, and no drift. Extrapolated or unvalidated results are
capped at low confidence and escalate during routing; unsupported regions are
excluded. Deployment feedback updates residuals and grows trust regions only
where real outcomes exist.

**Rationale:** Providers cannot certify their own credibility, and a model
that is valid in one wind band, version, or customer fleet is not automatically
valid elsewhere. Explicit evidence requirements keep findings defensible and
make extrapolation visible in the readiness report.

**Revisit when:** Enough deployment outcomes exist to calibrate probabilistic
trust or to justify controlled inheritance between closely related model
versions.


## ADR-023: One Golden Path with labelled stand-ins, separate from the core

**Decision:** Keep one canonical demo, `drone-eval agent` in
`drone_sim/agent_session.py`, that composes the existing production components
on `examples/demo_deployment/`. LLM-dependent stages use the same typed
contracts in live and recorded-replay modes. The hypothesis stand-in was
removed in BEN-79; generated proposals now traverse `generate_hypotheses`.
Thresholds from `golden_path.bind_thresholds` remain an explicitly labelled
stand-in until deterministic judges exist. No core semantic module imports the
operator-session layer.
Unimplemented stages are printed as not implemented instead of being simulated.
Tests are organized into component, integration, and golden layers, enforced
by `tests/conftest.py`.

**Rationale:** Agents were landing contracts and libraries faster than they
were being connected. Without one runnable path, it was unclear what worked
end to end, and architecture prose described planned stages as current. A
single honest path makes progress measurable: each milestone should make one
more stage real or remove a stand-in.

**Revisit when:** Judges exist (the remaining threshold stand-in should then
be deleted), or a real product entry point (API/UI, BEN-58–62)
supersedes the CLI as the primary demo surface.

## ADR-024: Provider-neutral, contract-validated hosted LLM edge

**Decision:** Put hosted LLM calls behind a small provider-neutral interface
with versioned prompts, task-selected model IDs, typed tool declarations, and
normalized responses. Validate every structured response directly against an
existing Pydantic contract. Return validation errors for a bounded number of
repairs, then fail closed. Read hosted-provider configuration from the
environment and leave all deterministic product paths usable when it is absent.

**Rationale:** Agentic discovery and hypothesis work need a real model edge,
but hosted text cannot become deployment facts, conflict resolutions, or test
plans without a typed boundary. Recording the prompt and model identity makes
later audit and replay possible without coupling core contracts to Anthropic.

**Revisit when:** A second provider requires a broader normalized response
model, durable call-ledger storage replaces in-memory response metadata, or
the customer-data safety policy (BEN-66) narrows the request payload further.

## ADR-025: Persistent hashed LLM ledger with fail-closed replay

**Decision:** Record every live or replayed LLM invocation atomically outside
the deployment folder. Entries retain prompt/request hashes, model identity,
explicit candidate and file-hash references, context-trace indices, response,
validation result, token usage, latency, and cost. Replay uses request hashes
and refuses a miss rather than making a network request. Apply configured
per-stage call, token, and cost budgets before live calls, stopping explicitly
when a limit is reached.

**Rationale:** Hosted LLM behavior must be auditable and testable without
network access or customer-byte duplication. Keeping request inputs as stable
references joins model decisions to the existing context audit trail, while
recording replay attempts prevents a test run from being mistaken for a live
investigation.

**Revisit when:** BEN-49 supplies a unified workflow-run store, BEN-66 settles
retention/encryption policy for recorded outputs, or pricing must be fetched
from a governed provider catalog rather than supplied as pinned configuration.

## ADR-026: Treat deployment content as untrusted LLM evidence

**Decision:** Require an explicit deployment policy before sending hosted LLM
requests. Redact configured patterns, delimit all untrusted text, and ledger
the hash of exactly what was sent. Accept LLM output only as typed proposals;
never expose conflict resolution, thresholds, or deterministic judgments as
model output contracts. Require inferred evidence to retain source anchors
that deterministic code verifies against source bytes.

**Rationale:** Operator-provided documents can contain prompt injection. This
boundary prevents their prose from becoming system authority while preserving
traceable, limited evidence proposals for later deterministic review.

## ADR-027: LLM applicability rules require explicit human approval

**Decision:** Let the LLM propose only versioned, deployment-bound typed
`EvidencePredicate` applicability rules for existing drone-taxonomy leaves.
Keep conservative baseline profiles unchanged. Merge proposals into a complete
profile set only after a named operator explicitly confirms a review; execute
the resulting rules exclusively in deterministic coverage code.

**Rationale:** Applicability can reduce the work that needs investigation, so
an unreviewed model suggestion must not silently hide a drone deployment risk.
The review record, taxonomy/deployment binding, and complete retained baseline
profiles make rule-outs auditable while preserving the distinction between a
ruled-out mechanism and missing evidence.

**Revisit when:** Validated domain rule sources and comparison-between-IR-path
predicates can express reviewed rules more directly without weakening the
human approval and deterministic evaluation boundary.
