# Capability ontology v0.1

The capability ontology is the vocabulary the planner uses to say *what* must
be computed to test a drone failure hypothesis, without saying *which* tool,
model, or simulator computes it. Providers (analytical models, geometry
engines, physics models, simulators, customer tools) register against these
capabilities separately.

## Granularity

A capability is one causal transformation with canonical typed inputs and
outputs, for example “integrate route energy demand under loading and wind”
(`energy.route_demand`) or “measure clearance of a flown trajectory to site
geometry” (`geometry.trajectory_clearance`). It is:

- coarse enough that several fidelity levels can implement it — a closed-form
  energy model and a physics simulation both provide `energy.route_demand`;
- fine enough that its outputs are meaningful to other capabilities and to
  deterministic judges; and
- free of fidelity, cost, runtime, and vendor information, which belong to
  providers in the registry.

Capability IDs are `<domain>.<name>`. The domain prefix must match the declared
`CapabilityDomain`: weather, geometry, dynamics, energy, sensing, navigation,
communication, autonomy, mission, external actors, rules, and uncertainty.

## Atomic and composite capabilities

Most capabilities are atomic. A composite names at least two atomic
components. When `closed_loop` is true, the components exchange feedback within
a time step — for example `autonomy.closed_loop_flight` couples trajectory
response, absolute positioning, observation synthesis, and failsafe response.
Such a composite must be supplied by a single provider or co-simulation; the
planner cannot chain its components as independent providers, and dependency
graphs therefore stay acyclic.

## Canonical data kinds

`DataKind` enumerates the values that need first-class canonical types because
they cross capability boundaries: deployment, route, trajectory, site geometry,
operating volume, wind field, atmosphere, vehicle envelope, battery state,
sensor observation, detection, localization estimate, link state, traffic,
condition samples, constraint violations, mission outcome, and measures.
Scalar observables such as `minimum_clearance_m` are named *measures* carried
by a `measure` output rather than separate data kinds. Concrete payload types
for each kind are defined by the typed-interface layer.

## Expressing hypotheses

`MechanismCapabilityMap` binds every failure-taxonomy leaf to the minimum set
of capabilities that can test it. `validate_against` checks that:

- every taxonomy leaf is bound exactly once and every binding names a known
  capability;
- each required capability's inputs are satisfiable from Deployment IR or from
  another required capability; and
- the required capabilities' measures cover every observable outcome the
  taxonomy leaf declares.

The ontology rejects capability IDs, names, and descriptions that mention
simulator or vendor tools. A binding is a minimum credible requirement, not a
fidelity choice: routing may later satisfy the same capability with a
higher-fidelity provider or substitute a closed-loop composite.
