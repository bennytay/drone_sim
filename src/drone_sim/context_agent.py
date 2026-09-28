"""Replayable, bounded evidence-search policy over deterministic context tools."""
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field
from datetime import UTC, datetime
from drone_sim.context import DeploymentState, InspectionEvent
class ContextActionKind(StrEnum): SEARCH = "search"; STOP = "stop"; ASK = "ask"
class ContextAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ContextActionKind
    field: str | None = None
    rationale: str = Field(min_length=1)
class ContextStopReason(StrEnum): READY="ready"; BUDGET="budget_exhausted"; NO_EVIDENCE="no_promising_evidence"
class ContextPolicy:
    """Deterministic fallback policy; an LLM may propose the same typed action."""
    def choose(self, unresolved: tuple[str, ...], *, calls_used: int, max_calls: int) -> ContextAction:
        if not unresolved: return ContextAction(kind=ContextActionKind.STOP, rationale=ContextStopReason.READY.value)
        if calls_used >= max_calls: return ContextAction(kind=ContextActionKind.STOP, rationale=ContextStopReason.BUDGET.value)
        return ContextAction(kind=ContextActionKind.SEARCH, field=unresolved[0].split("/")[1], rationale="Highest-priority unresolved deployment field")

def record_action(state: DeploymentState, action: ContextAction) -> None:
    """Persist the policy decision in the same audit trail as evidence inspection."""
    state.trace.append(InspectionEvent(timestamp=datetime.now(UTC), field=action.field or "agent", query=action.kind.value, source_path=None, reason=action.rationale, outcome="unresolved" if action.kind != ContextActionKind.SEARCH else "no_candidate"))
