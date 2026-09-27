# Provenance and uncertainty v0.1

`EvidenceBackedDeployment` is the required handoff for a reconstructed drone
deployment. It contains an unchanged Deployment IR plus a validated evidence
graph. The envelope, not a bare Deployment IR, crosses into hypothesis,
scenario, execution, and reporting stages.

## Material-field coverage

Every populated scalar Deployment IR field except `schema_version` is material
and must have exactly one `MaterialFact`. A fact is addressed by an RFC 6901
JSON Pointer such as `/vehicle/mass_kg` or
`/mission/route/points/0/position/altitude_m`. Empty collections and absent
optional fields do not create facts.

The selected candidate's value must equal the canonical value at that path.
Other credible values remain in `competing`; they are never silently dropped.
Validation rejects missing or extra paths and duplicate candidate IDs.

## Evidence candidates

Each candidate records:

- a stable ID for downstream lineage;
- its value origin: observed, manufacturer-specified, inferred, estimated,
  model-derived, or assumed;
- exact source locations plus source-byte SHA-256 hashes;
- a named, versioned extraction method;
- ordinal confidence (`high`, `medium`, `low`, or `unknown`) and a required
  plain-language basis;
- referenced explicit assumptions; and
- input candidate IDs for derived values.

Observed and manufacturer-specified values require source anchors. Assumed
values require a declared assumption. Inferred, estimated, and model-derived
values require a source, an assumption, or upstream lineage. Dangling
references, self-reference, and derivation cycles are invalid.

Confidence is deliberately qualitative. These levels prioritize review and
fidelity escalation; they are not calibrated probabilities and must not be
treated as such.

## Exact source anchors

All fields require anchoring because any populated value may affect hypothesis
selection or a later test. An anchor includes a bundle-relative source path,
the source bytes' SHA-256 hash, a location kind, and an exact locator. Supported
locations include JSON Pointers, text line ranges, PDF pages, table cells, byte
ranges, and adapter-defined locators.

The local-folder JSON adapter emits a distinct anchor for every scalar leaf.
For example, vehicle mass extracted from a manifest is anchored at
`/vehicle/mass_kg`, not merely to the manifest file.

## Downstream preservation

Scenario inputs and findings should cite candidate IDs, not copy provenance
text. Model-derived values cite their input IDs, so a readiness claim can be
traced recursively to source bytes or explicit assumptions. Schema migrations
must update field paths explicitly while preserving candidate IDs whenever the
underlying evidence and meaning are unchanged.
