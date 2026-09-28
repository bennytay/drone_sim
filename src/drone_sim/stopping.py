"""Explicit stopping and residual-risk decisions for drone investigations."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from drone_sim.coverage import CoverageMap
from drone_sim.ir import StrictModel


class StopReason(StrEnum):
    COMPLETE = "complete"
    BUDGET = "budget"
    UNRESOLVED = "unresolved"
    HUMAN_REVIEW = "human_review"


class StopDecision(StrictModel):
    stop: bool
    reason: StopReason
    residuals: tuple[str, ...] = ()
    novelty: float = Field(ge=0, le=1)


class StopPolicy(StrictModel):
    max_actions: int = Field(gt=0)
    min_novelty: float = Field(ge=0, le=1)
    require_human_on_disagreement: bool = True


def decide_stop(
    coverage: CoverageMap,
    *,
    actions: int,
    novelty: float,
    disagreement: bool,
    policy: StopPolicy,
) -> StopDecision:
    residual = [f"{e.mechanism_id}: {e.state.value}" for e in coverage.unexplored]
    if disagreement and policy.require_human_on_disagreement:
        return StopDecision(
            stop=True,
            reason=StopReason.HUMAN_REVIEW,
            residuals=tuple(residual),
            novelty=novelty,
        )
    if actions >= policy.max_actions:
        return StopDecision(
            stop=True,
            reason=StopReason.BUDGET,
            residuals=tuple(residual),
            novelty=novelty,
        )
    if not residual and novelty < policy.min_novelty:
        return StopDecision(stop=True, reason=StopReason.COMPLETE, novelty=novelty)
    return StopDecision(
        stop=False,
        reason=StopReason.UNRESOLVED,
        residuals=tuple(residual),
        novelty=novelty,
    )
