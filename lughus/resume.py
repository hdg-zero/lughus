"""Safe resume decisions at durable execution boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .persistence import Checkpoint


class ResumeAction(StrEnum):
    CONTINUE = "continue"
    RETRY_SAFE_ACTION = "retry_safe_action"
    REQUIRE_RECONCILIATION = "require_reconciliation"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    action: ResumeAction
    reason: str


def decide_resume(checkpoint: Checkpoint, *, pending_action_idempotent: bool = False) -> ResumeDecision:
    if checkpoint.outcome_unknown:
        if pending_action_idempotent:
            return ResumeDecision(ResumeAction.RETRY_SAFE_ACTION, "idempotent outcome may be retried")
        return ResumeDecision(ResumeAction.REQUIRE_RECONCILIATION,
                              "non-idempotent action has an unknown outcome")
    if checkpoint.pending_action:
        return ResumeDecision(ResumeAction.CONTINUE, "resume before pending action dispatch")
    return ResumeDecision(ResumeAction.CONTINUE, "resume from the latest safe boundary")
