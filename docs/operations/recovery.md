> [← Documentation index](../index.md)

# Execution Recovery Guide

Lughus agents are designed to survive interruptions and network failures. The framework's contracts — checkpoints, idempotency receipts, and approval records — are designed so that a durable backend can resume runs predictably. The bundled in-memory implementations are compliance references and are explicitly not durable (see `docs/architecture/ADR-006-persistence.md`).

## Checkpoint Boundaries
Execution state is snapshotted into a `Checkpoint` object (`lughus.persistence`) at specific, safe boundaries:
- **Tool Proposal:** Before a tool executes, the checkpoint carries `pending_action` and `pending_arguments_hash`.
- **Unknown Outcomes:** When an execution is interrupted before its result is known, the checkpoint carries `outcome_unknown`.
- **Approval Waits:** While waiting for human interaction, a run transitions to `WAITING` through the `RunCoordinator`.

## Interrupted Tool Calls
The recovery semantics for an interrupted tool call depend on whether the tool was registered as idempotent:

- **Idempotent tools** carry an idempotency key derived from `(run_id, tool_name, arguments)`. If a receipt exists in a durable `IdempotencyStore`, re-execution returns the recorded result instead of running the tool again. A receipt left `PENDING` by a crashed process expires after `pending_ttl_seconds` and can then be claimed again.
- **Non-idempotent tools with unknown outcomes** must never be retried blindly: dual execution cannot be ruled out. The `outcome_unknown` flag on the checkpoint marks the run for reconciliation, and the framework halts instead of guessing.

## Manual Reconciliation Workflow
To unblock a run whose checkpoint has `outcome_unknown` set:
1. The operator queries the external system to verify if the action succeeded.
2. The operator injects a synthetic tool-result event representing the true outcome into the `EventStore`.
3. The operator updates the `Checkpoint` state to clear the pending action.
4. The run is re-queued and resumes normally as if it had received the result natively.

Application developers own this workflow: lughus enforces the halt but does not automate external-state verification.

---

**Related:** [ADR-006 — Persistence](../architecture/ADR-006-persistence.md) · [Scaling](scaling.md)
