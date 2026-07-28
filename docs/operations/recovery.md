# Execution Recovery Guide

Lughus agents are designed to survive process restarts and network failures. The framework relies on a durable checkpointing strategy to resume runs predictably.

## Checkpoint Boundaries
Execution state is snapshotted into a `Checkpoint` object (`lughus.persistence`) at specific, safe boundaries:
- **Before and After Model Calls:** Safely pauses while waiting for LLM generation.
- **Tool Proposal and Completion:** Before a tool executes, and immediately after it returns.
- **Approval Waits:** When execution yields pending human interaction.

## The Resume Decision Tree
When Lughus loads a paused run, the `decide_resume` function evaluates the last known checkpoint to determine the `ResumeAction`.
1. `CONTINUE`: Resumes standard execution from the latest safe boundary. Used if no action was pending.
2. `RETRY_SAFE_ACTION`: If an idempotent tool failed or was interrupted, Lughus automatically retries it.
3. `REQUIRE_RECONCILIATION`: If a non-idempotent action was interrupted (e.g., a POST request to an external billing API) and the outcome is unknown, execution halts and requests manual intervention.

## Unknown Outcomes
When a process crashes mid-execution of a non-idempotent tool, the `outcome_unknown` flag is set. Lughus cannot blindly retry without risking dual execution. The framework enforces a halt. Application developers must implement reconciliation strategies, such as querying the external system for state before manually injecting the result back into the event stream.

## Manual Intervention Workflow
To unblock a run stuck in `REQUIRE_RECONCILIATION`:
1. The operator queries the external system to verify if the action succeeded.
2. The operator injects a synthetic tool result event representing the true outcome into the `EventStore`.
3. The operator updates the `Checkpoint` state to clear the pending action.
4. The run is re-queued and resumes normally as if it had received the result natively.
