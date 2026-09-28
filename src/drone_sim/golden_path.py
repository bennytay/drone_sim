"""Golden Path: run every implemented stage on one deployment folder.

This module composes existing components; it adds no evaluation semantics of
its own beyond two clearly labelled pieces of demo wiring:

- hypotheses are loaded from a hand-authored file because no hypothesis
  generator exists yet; and
- decision thresholds are bound from Deployment IR constraints and success
  criteria by a small fixed table because no deterministic judge exists yet.

Everything else — context reconstruction, readiness, coverage, planning,
execution, and fidelity routing — is the production code path.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from drone_sim.capabilities import DataKind
from drone_sim.context import ContextOrchestrator, DeploymentState
from drone_sim.coverage import ApplicabilityStatus, CoverageMap, assess_coverage
from drone_sim.graph import EvaluationGoal
from drone_sim.hypothesis import HypothesisGenerationContract
from drone_sim.hypothesis import HypothesisStatus
from drone_sim.investigation import (
    InvestigationAction,
    InvestigationState,
    next_action,
)
from drone_sim.ir import DeploymentIR
from drone_sim.provenance import EvidenceBackedDeployment
from drone_sim.reconstruction import ClarificationRequest
from drone_sim.reference_tools import BUILTIN_TOOLS
from drone_sim.registry import OperatingContext, ToolRegistry
from drone_sim.routing import (
    Comparator,
    DecisionThreshold,
    FidelityRouter,
    RoutingOutcome,
)
from drone_sim.validation import ReadinessReport


# Stages of the intended product flow that have no implementation yet. They
# are printed so the demo never implies more than exists.
NOT_IMPLEMENTED = (
    ("Hypothesis generation", "no generator turns Deployment IR into hypotheses (BEN-14/15 define only the contract)"),
    ("Deterministic judges", "no versioned judge binds measures to verdicts (BEN-36/37)"),
    ("Scenario Spec", "no simulator-agnostic scenario contract (BEN-24)"),
    ("Isaac Sim / Isaac Lab", "only a manifest in examples/tool_manifests; no adapter (BEN-25/26)"),
    ("Scenario variation and boundary search", "only the nominal condition is evaluated (BEN-38/39)"),
    ("Readiness report", "no operator-facing report model or generator (BEN-40/41)"),
)


@dataclass(frozen=True)
class BoundThreshold:
    threshold: DecisionThreshold
    basis: str


@dataclass(frozen=True)
class HypothesisRun:
    hypothesis_id: str
    mechanism_id: str
    goal: EvaluationGoal
    thresholds: tuple[BoundThreshold, ...]
    outcome: RoutingOutcome


@dataclass
class GoldenPathResult:
    root: Path
    work_dir: Path
    files_indexed: int
    state: DeploymentState
    evidence: EvidenceBackedDeployment | None
    readiness: ReadinessReport
    clarifications: tuple[ClarificationRequest, ...]
    coverage: CoverageMap | None = None
    hypotheses: HypothesisGenerationContract | None = None
    hypotheses_path: Path | None = None
    first_action: InvestigationAction | None = None
    runs: tuple[HypothesisRun, ...] = ()
    artifacts: list[Path] = field(default_factory=list)

    @property
    def stopped_at_context(self) -> bool:
        return self.evidence is None or not self.readiness.ready


def builtin_toolbox() -> tuple[ToolRegistry, dict]:
    registry = ToolRegistry()
    tools = {}
    for tool in BUILTIN_TOOLS:
        registry.register(tool.manifest)
        tools[tool.manifest.key] = tool
    return registry, tools


def operating_context(deployment: DeploymentIR) -> OperatingContext:
    variables = {}
    if deployment.conditions and deployment.conditions.wind_speed_mps is not None:
        variables["wind_speed_mps"] = deployment.conditions.wind_speed_mps
    return OperatingContext(airframe=deployment.vehicle.airframe, variables=variables)


def bind_thresholds(
    deployment: DeploymentIR, measures: tuple[str, ...]
) -> tuple[BoundThreshold, ...]:
    """Demo wiring: derive decision thresholds from Deployment IR.

    This stands in for the deterministic judge layer (BEN-37). It covers only
    the measures the Golden Path hypotheses use.
    """

    bound: list[BoundThreshold] = []
    energy = {
        constraint.unit: (constraint.id, float(constraint.value))
        for constraint in deployment.constraints
        if constraint.category == "energy"
        and isinstance(constraint.value, int | float)
    }
    if "remaining_energy_wh" in measures and "Wh" in energy and "1" in energy:
        (usable_id, usable), (reserve_id, fraction) = energy["Wh"], energy["1"]
        bound.append(
            BoundThreshold(
                DecisionThreshold(
                    measure="remaining_energy_wh",
                    comparator=Comparator.GTE,
                    value=usable * fraction,
                    unit="Wh",
                ),
                f"constraint {reserve_id} ({fraction:g}) x {usable_id} ({usable:g} Wh)",
            )
        )
    if "mass_margin_kg" in measures and deployment.vehicle.max_takeoff_mass_kg:
        bound.append(
            BoundThreshold(
                DecisionThreshold(
                    measure="mass_margin_kg",
                    comparator=Comparator.GTE,
                    value=0.0,
                    unit="kg",
                ),
                "takeoff mass must not exceed /vehicle/max_takeoff_mass_kg",
            )
        )
    if "minimum_clearance_m" in measures:
        for criterion in deployment.success_criteria:
            if criterion.metric == "obstacle_clearance_m" and isinstance(
                criterion.target, int | float
            ):
                bound.append(
                    BoundThreshold(
                        DecisionThreshold(
                            measure="minimum_clearance_m",
                            comparator=Comparator.GTE,
                            value=float(criterion.target),
                            unit="m",
                        ),
                        f"success criterion {criterion.id}",
                    )
                )
    return tuple(bound)


def run_golden_path(
    root: Path,
    work_dir: Path,
    hypotheses_path: Path | None = None,
    *,
    fresh: bool = False,
) -> GoldenPathResult:
    root = root.resolve(strict=True)
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(root):
        raise ValueError("work directory must be outside the read-only deployment folder")
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / "state.json"
    if fresh and state_path.exists():
        state_path.unlink()

    # Stages 1-3: context reconstruction and readiness (production code).
    orchestrator = ContextOrchestrator(root, state_path)
    evidence, state = orchestrator.run()
    readiness = orchestrator.assess(state)
    result = GoldenPathResult(
        root=root,
        work_dir=work_dir,
        files_indexed=len(orchestrator.index.records),
        state=state,
        evidence=evidence,
        readiness=readiness,
        clarifications=orchestrator.clarification_requests(state),
        artifacts=[state_path],
    )
    _write(result, "context_readiness.json", readiness)
    if result.stopped_at_context:
        return result
    assert evidence is not None
    _write(result, "evidence.json", evidence)
    deployment = evidence.deployment

    # Stage 4: failure-mechanism applicability (production code).
    result.coverage = assess_coverage(deployment)
    _write(result, "coverage.json", result.coverage)

    # Stage 5: hypotheses. No generator exists; only a hand-authored file.
    if hypotheses_path is None:
        return result
    result.hypotheses_path = hypotheses_path
    result.hypotheses = HypothesisGenerationContract.model_validate_json(
        hypotheses_path.read_text()
    )
    _write(result, "hypotheses.json", result.hypotheses)
    result.first_action = next_action(
        InvestigationState(
            hypotheses=result.hypotheses.hypotheses, coverage=result.coverage
        )
    )

    # Stages 6-8: planning, execution, fidelity routing (production code),
    # with thresholds bound by the demo wiring above.
    registry, tools = builtin_toolbox()
    router = FidelityRouter(registry, tools)
    context = operating_context(deployment)
    runs = []
    for hypothesis in result.hypotheses.hypotheses:
        if hypothesis.status in {HypothesisStatus.REJECTED, HypothesisStatus.MERGED}:
            continue
        goal = EvaluationGoal.for_hypothesis(hypothesis)
        thresholds = bind_thresholds(deployment, goal.measures)
        outcome = router.investigate(
            goal,
            context,
            tuple(item.threshold for item in thresholds),
            {DataKind.DEPLOYMENT: deployment},
        )
        runs.append(
            HypothesisRun(
                hypothesis_id=hypothesis.id,
                mechanism_id=hypothesis.mechanism_id,
                goal=goal,
                thresholds=thresholds,
                outcome=outcome,
            )
        )
        _write(result, f"routing/{hypothesis.id}.json", outcome)
    result.runs = tuple(runs)
    return result


def _write(result: GoldenPathResult, name: str, value: BaseModel) -> None:
    path = result.work_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2) + "\n")
    result.artifacts.append(path)


# --------------------------------------------------------------------------
# Rendering


REAL = "✅ implemented"
WIRING = "🟡 demo wiring"
FIXTURE = "🟡 hand-authored input"
MISSING = "⚪ not implemented"


def render(result: GoldenPathResult, *, verbose: bool = False) -> str:
    out: list[str] = []

    def stage(number: int, title: str, status: str) -> None:
        out.append("")
        out.append(f"[{number}] {title}  ({status})")

    out.append("Drone deployment verification — Golden Path")
    out.append(f"Deployment folder: {result.root}")
    out.append(f"Work directory:    {result.work_dir}")

    state = result.state
    stage(1, "Context discovery", REAL)
    parsed = Counter(source.adapter for source in state.parsed_sources.values())
    errors = [event for event in state.trace if event.outcome == "parse_error"]
    out.append(f"  files indexed: {result.files_indexed}; files opened: {len(state.inspected_paths)}")
    out.append("  adapters used: " + ", ".join(f"{name} x{count}" for name, count in sorted(parsed.items())))
    out.append(f"  inspection events: {len(state.trace)}; parse errors: {len(errors)}")
    for link in state.entity_links:
        out.append(
            f"  linked {link.entity_type} '{link.canonical_value}' across {len(link.source_paths)} files"
        )

    evidence = result.evidence
    stage(2, "Deployment IR reconstruction", REAL)
    if evidence is None:
        out.append("  Deployment IR could not be built from the evidence found.")
    else:
        out.extend(_describe_deployment(evidence, state))

    stage(3, "Context readiness gate (drone_hypothesis_generation_v1)", REAL)
    readiness = result.readiness
    out.append(f"  status: {readiness.status.value.upper()}")
    for finding in readiness.findings:
        out.append(f"  - {finding.code.value} {finding.path}: {finding.message}")
    for request in result.clarifications:
        out.append(f"  ? ask operator [{request.field}]: {request.question}")
    if result.stopped_at_context:
        out.append("")
        out.append("PIPELINE STOPPED: context is not ready, so no hypotheses or tests were run.")
        out.extend(_footer(result))
        return "\n".join(out)

    coverage = result.coverage
    assert coverage is not None
    stage(4, "Failure-mechanism applicability (taxonomy v" + coverage.taxonomy_version + ")", REAL)
    counts = Counter(entry.applicability for entry in coverage.entries)
    out.append(
        f"  {len(coverage.entries)} mechanisms: {counts[ApplicabilityStatus.APPLIES]} applies, "
        f"{counts[ApplicabilityStatus.UNKNOWN]} unknown, "
        f"{counts[ApplicabilityStatus.RULED_OUT]} ruled out"
    )
    out.append("  note: default profiles only check that the required IR context exists,")
    out.append("        so most mechanisms 'apply' whenever the IR is complete.")
    for entry in coverage.entries:
        if entry.applicability != ApplicabilityStatus.APPLIES or verbose:
            missing = [a.predicate.path for a in entry.evidence if a.result is None]
            detail = f" (missing {', '.join(missing)})" if missing else ""
            out.append(f"  - {entry.applicability.value:9} {entry.mechanism_id}{detail}")
    for risk in coverage.residual_unknowns:
        out.append(f"  residual risk: {risk.id} — {risk.reason}")

    hypotheses = result.hypotheses
    stage(5, "Failure hypotheses", f"{MISSING} generator; {FIXTURE}")
    if hypotheses is None:
        out.append("  No hypothesis generator exists. Pass --hypotheses FILE to continue")
        out.append("  with hand-authored hypotheses (see examples/demo_hypotheses.json).")
        out.append("")
        out.append("PIPELINE STOPPED after applicability: no hypotheses to test.")
        out.extend(_footer(result))
        return "\n".join(out)
    out.append(f"  loaded {len(hypotheses.hypotheses)} hand-authored hypotheses from {result.hypotheses_path}")
    for hypothesis in hypotheses.hypotheses:
        out.append(f"  - {hypothesis.id}  [{hypothesis.materiality.value} materiality]")
        out.append(f"      mechanism: {hypothesis.mechanism_id}")
        out.append(f"      why: {' -> '.join(hypothesis.causal_path)}")
    if result.first_action:
        action = result.first_action
        out.append(
            f"  investigation policy next action: {action.kind.value} {action.hypothesis_id} "
            f"at fidelity level {action.fidelity} ({action.reason})"
        )

    stage(6, "Test selection, execution, and fidelity routing", f"{REAL}; thresholds: {WIRING}")
    for run in result.runs:
        out.extend(_describe_run(run, verbose))

    stage(7, "Summary of executed evaluations", "🟡 demo summary — NOT a readiness verdict")
    applicable = counts[ApplicabilityStatus.APPLIES]
    for run in result.runs:
        out.append(f"  {run.hypothesis_id}: {_verdict_line(run)}")
    out.append(
        f"  mechanisms evaluated: {len(result.runs)} of {applicable} applicable; "
        f"{applicable - len(result.runs)} remain unexamined"
    )
    out.append("  only nominal conditions were evaluated; no variation or boundary search ran")
    out.extend(_footer(result))
    return "\n".join(out)


def _describe_deployment(
    evidence: EvidenceBackedDeployment, state: DeploymentState
) -> list[str]:
    d = evidence.deployment
    v = d.vehicle
    lines = [
        f"  deployment: {d.deployment_id}",
        f"  aircraft:   {v.id} — {v.manufacturer or '?'} {v.model or ''} ({v.airframe}), "
        f"{v.mass_kg} kg, MTOM {v.max_takeoff_mass_kg} kg, wind limit {v.max_wind_speed_mps} m/s",
    ]
    for payload in d.payloads:
        lines.append(f"  payload:    {payload.id} ({payload.kind}, {payload.mass_kg} kg)")
    points = d.mission.route.points
    top = max(point.position.altitude_m for point in points)
    lines.append(f"  mission:    {d.mission.name} — {d.mission.objective}")
    lines.append(
        f"  route:      {len(points)} waypoints, max {top} m ({points[0].position.altitude_reference})"
    )
    lines.append(f"  site:       {d.site.name}; {len(d.site.artifacts)} site artifact(s)")
    if d.conditions:
        c = d.conditions
        lines.append(
            f"  conditions: wind {c.wind_speed_mps} m/s from {c.wind_direction_deg} deg, "
            f"{c.temperature_c} C, visibility {c.visibility_m} m"
        )
    lines.append(f"  autonomy:   {d.autonomy.mode} via {d.autonomy.controller} {d.autonomy.version or ''}")
    for constraint in d.constraints:
        value = "" if constraint.value is None else f" = {constraint.value} {constraint.unit or ''}"
        lines.append(f"  constraint: {constraint.id} [{constraint.category}]{value}")
    for criterion in d.success_criteria:
        lines.append(
            f"  success:    {criterion.id}: {criterion.metric} {criterion.operator} "
            f"{criterion.target} {criterion.unit or ''}"
        )
    lines.append(
        f"  references: {len(d.telemetry)} telemetry, {len(d.raw_data)} raw data, {len(d.models)} models"
    )
    absent = [
        name
        for name in ("payloads", "conditions", "constraints", "telemetry", "raw_data", "models")
        if not getattr(d, name)
    ]
    lines.append(f"  missing/empty optional sections: {', '.join(absent) or 'none'}")
    competing = [fact for fact in evidence.facts if fact.competing]
    lines.append(
        f"  evidence: {len(evidence.facts)} material facts, each anchored to a source; "
        f"{len(competing)} with competing values"
    )
    for path in ("/vehicle/mass_kg", "/conditions/wind_speed_mps"):
        try:
            anchor = evidence.fact(path).selected
        except KeyError:
            continue
        source = anchor.sources[0]
        lines.append(
            f"  e.g. {path} = {anchor.value}  <- {source.source_path}#{source.locator} "
            f"({anchor.extraction.name}, {anchor.uncertainty.confidence.value} confidence)"
        )
    return lines


def _describe_run(run: HypothesisRun, verbose: bool) -> list[str]:
    outcome = run.outcome
    final = outcome.final
    plan = final.record.plan
    lines = [f"  {run.hypothesis_id} -> measures {', '.join(run.goal.measures)}"]
    if plan.nodes:
        lines.append("    plan: " + " -> ".join(node.capability_id for node in plan.nodes))
        providers = sorted(set(final.providers.values()))
        lines.append("    providers: " + ", ".join(providers))
    for gap in plan.gaps:
        lines.append(f"    GAP {gap.kind.value}: {gap.subject} — {gap.reason}")
    for node in final.record.nodes:
        if node.status.value != "succeeded":
            lines.append(f"    node {node.node_id}: {node.status.value} {node.error or ''}")
    for measure in final.record.evidence:
        error = f" ± {measure.error.value:.3g}" if measure.error else ""
        value = measure.value if isinstance(measure.value, bool) else f"{measure.value:.3f}"
        lines.append(f"    measure {measure.name} = {value}{error} {measure.unit or ''} [{measure.provider_key}]")
    for bound in run.thresholds:
        t = bound.threshold
        lines.append(f"    threshold {t.measure} {t.comparator.value} {t.value:g} {t.unit or ''} (from {bound.basis})")
    if not run.thresholds:
        lines.append("    threshold: none bound (no judge binding for these measures)")
    for assessment in final.assessments:
        lines.append(f"    boundary {assessment.measure}: {assessment.status.value} — {assessment.reason}")
    lines.append(
        f"    routing decision: {final.decision.value} after {len(outcome.steps)} level(s); "
        f"review required: {'yes' if outcome.requires_review else 'no'}"
    )
    if verbose:
        lines.extend(f"    select: {line}" for line in final.selection)
        lines.extend(f"    why: {line}" for line in final.justification)
    return lines


def _verdict_line(run: HypothesisRun) -> str:
    final = run.outcome.final
    if not final.record.plan.complete:
        return "NOT EVALUATED — required capabilities have no registered provider"
    parts = []
    for assessment in final.assessments:
        if assessment.margin is None:
            parts.append(f"{assessment.measure}: no evidence")
            continue
        side = "satisfied" if assessment.margin >= 0 else "VIOLATED"
        parts.append(
            f"{assessment.measure} threshold {side} (margin {assessment.margin:+.3g}; "
            f"{assessment.status.value})"
        )
    if run.outcome.requires_review:
        parts.append("router requests review")
    return "; ".join(parts) or "no threshold bound"


def _footer(result: GoldenPathResult) -> list[str]:
    lines = ["", "Not implemented yet (the pipeline does not run these):"]
    lines.extend(f"  {MISSING}: {name} — {why}" for name, why in NOT_IMPLEMENTED)
    lines.append("")
    lines.append("Artifacts written:")
    lines.extend(f"  {path}" for path in result.artifacts)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drone-eval",
        description="Run every implemented verification stage on a drone deployment folder.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    analyse = commands.add_parser(
        "analyse", aliases=["analyze"], help="Analyse a read-only deployment folder"
    )
    analyse.add_argument("root", type=Path, help="Read-only deployment folder")
    analyse.add_argument(
        "--hypotheses",
        type=Path,
        help="Hand-authored hypotheses JSON (no generator exists yet)",
    )
    analyse.add_argument(
        "--work-dir",
        type=Path,
        help="Where state and artifacts are written (default: ./work/<folder name>)",
    )
    analyse.add_argument(
        "--fresh", action="store_true", help="Discard persisted state and re-read all evidence"
    )
    analyse.add_argument(
        "--verbose", action="store_true", help="Show every mechanism and routing justification"
    )
    agent = commands.add_parser(
        "agent", help="Run the persisted agentic operator session on a deployment folder"
    )
    agent.add_argument("root", type=Path, help="Read-only deployment folder")
    agent.add_argument("--work-dir", type=Path, help="Where session state and artifacts are written")
    agent.add_argument("--answers", type=Path, help="Optional non-interactive JSON answers file")
    agent.add_argument(
        "--replay-hypotheses", type=Path,
        help="Validated offline/replay hypotheses; demo defaults to its bundled replay fixture",
    )
    agent.add_argument("--fresh", action="store_true", help="Discard cached context state")
    args = parser.parse_args(argv)

    if args.command == "agent":
        from drone_sim.agent_session import render_agent_session, run_agent_session

        work_dir = args.work_dir or Path("work") / args.root.resolve().name
        try:
            state, result = run_agent_session(
                args.root, work_dir, answers_path=args.answers,
                replay_hypotheses=args.replay_hypotheses, fresh=args.fresh,
            )
        except (OSError, ValueError) as error:
            print(f"drone-eval: {error}", file=sys.stderr)
            return 1
        print(render_agent_session(state, result))
        return 2 if result.stopped_at_context else 0

    work_dir = args.work_dir or Path("work") / args.root.resolve().name
    try:
        result = run_golden_path(
            args.root, work_dir, args.hypotheses, fresh=args.fresh
        )
    except (OSError, ValueError) as error:
        print(f"drone-eval: {error}", file=sys.stderr)
        return 1
    print(render(result, verbose=args.verbose))
    return 2 if result.stopped_at_context else 0


if __name__ == "__main__":
    raise SystemExit(main())
