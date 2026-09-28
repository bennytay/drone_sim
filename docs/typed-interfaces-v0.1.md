# Canonical typed interfaces v0.1

Independently built drone models compose through canonical payload types, not
through point-to-point integrations. Every `DataKind` in the capability
ontology maps to exactly one Pydantic payload type in `PAYLOAD_TYPES`:

| Kind | Payload |
| --- | --- |
| deployment | `DeploymentIR` |
| route / trajectory | `CanonicalRoute`, `Trajectory` of `VehicleState` |
| site geometry / operating volume | `SiteGeometry`, `OperatingVolume` (boxes plus referenced mesh) |
| wind field / atmosphere | `WindField`, `Atmosphere` |
| vehicle envelope / battery state | `VehicleEnvelope`, `BatteryState` |
| sensor observation / detection / localization | `SensorObservation`, `DetectionSet`, `LocalizationEstimate` |
| link state / traffic | `LinkState`, `Traffic` |
| condition samples | `ConditionSamples` |
| constraint violation / mission outcome | `ConstraintViolations`, `MissionOutcome` |
| measure | `MeasureSet` of named `Measure` values with optional error |

## Mandatory conventions

- **Units:** SI, encoded in field and measure names (`_m`, `_mps`, `_wh`, `_s`,
  `_deg`, `_kg`). Unit conversion happens in source adapters, never in models.
- **Frame:** positions are local East-North-Up metres in a `LocalFrame`
  anchored at a geodetic origin with an explicit vertical reference. Every
  positional payload in one invocation must share the same frame; mixing
  frames is an `InterfaceError`, and a provider may not change the frame.
- **Time:** seconds relative to the UTC `epoch` carried by the time-indexed
  payload.
- **Direction:** degrees clockwise from true north. Wind direction is the
  meteorological direction the wind blows *from*.

## Large data by reference

Payloads carry at most `MAX_INLINE_SAMPLES` samples inline. Larger time series,
sensor frames, wind grids, and meshes travel as `SeriesRef` or `ArtifactRef`.
`SeriesRef` must pin a SHA-256 digest and declare its fields, sample count, and
time span so consumers can validate and reproduce results without copying data
through the planner.

## Semantic conversion versus model adaptation

Semantic conversion from Deployment IR into canonical payloads is itself a
registered provider (`builtin.deployment-semantics`) for route projection,
vehicle envelope, atmosphere, and wind-field capabilities. Model-specific
adaptation — native APIs, file formats, units, or coordinate conventions of a
particular model or simulator — lives entirely inside that provider's
`ToolAdapter.compute` and never crosses the canonical boundary.

`ToolAdapter.invoke` resolves the manifest against the ontology, validates each
input and output against its port type, enforces the shared frame, and rejects
measures the provision does not declare. `run_steps` wires providers purely by
data kind: each step reads inputs from, and writes outputs to, a kind-keyed
store, and measure sets accumulate. No provider knows which provider produced
its inputs.

## Reference providers

- `builtin.deployment-semantics` (rule): Deployment IR to canonical payloads.
  Takeoff mass is vehicle mass plus payload masses. Until Deployment IR carries
  battery fields, usable energy is read from an `energy` constraint in `Wh` and
  the landing reserve fraction from an `energy` constraint with unit `1`.
- `builtin.momentum-energy` (analytical, multirotor): momentum-theory hover
  power plus parasitic drag and climb power integrated per leg in steady wind,
  with a declared 15 % relative error, and reserve assessment.
- `builtin.swept-volume` (geometric): sampled clearance from the vehicle's
  extent to box obstacles and ground.

Together with any third-party site provider, these run an end-to-end energy
reserve and route clearance graph from Deployment IR to measures without
bespoke tool-to-tool code.
