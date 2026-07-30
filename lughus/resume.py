"""Safe resume decisions at durable execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .idempotency import AttemptStatus, IdempotencyKey, IdempotencyStore
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


async def decide_resume(
    checkpoint: Checkpoint,
    *,
    pending_action_idempotent: bool = False,
    idempotency_store: IdempotencyStore | None = None,
    run_id: str | None = None,
) -> ResumeDecision:
    """Determine the safest action when resuming from a checkpoint.

    When an ``idempotency_store`` is provided, the function checks whether a
    completed receipt already exists for the pending action.  If so, the run
    can safely continue without re-executing the tool.
    """
    if checkpoint.outcome_unknown:
        if (
            idempotency_store is not None
            and checkpoint.pending_action
            and checkpoint.pending_arguments_hash
        ):
            key = IdempotencyKey(
                run_id=run_id or checkpoint.run_id,
                tool_name=checkpoint.pending_action,
                arguments_hash=checkpoint.pending_arguments_hash,
            )
            attempt = await idempotency_store.get(key)
            if attempt is not None and attempt.status == AttemptStatus.COMPLETED:
                return ResumeDecision(
                    ResumeAction.COMPLETE, "idempotency receipt proves completion"
                )
        if pending_action_idempotent:
            return ResumeDecision(
                ResumeAction.RETRY_SAFE_ACTION, "idempotent outcome may be retried"
            )
        return ResumeDecision(
            ResumeAction.REQUIRE_RECONCILIATION,
            "non-idempotent action has an unknown outcome",
        )
    if checkpoint.pending_action:
        return ResumeDecision(ResumeAction.CONTINUE, "resume before pending action dispatch")
    return ResumeDecision(ResumeAction.CONTINUE, "resume from the latest safe boundary")
