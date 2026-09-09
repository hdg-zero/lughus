# Durable execution and resumption (0.21)

The integrated reference implementation is SQLiteStore on a local filesystem.
This is **not** multi-replica/distributed execution and does not claim universal
exactly-once external effects. Enable it explicitly through AgentRuntime.journal.

```python
store = SQLiteStore("/srv/lughus/runs.db")
runtime = AgentRuntime(
    execution=ExecutionRuntime(), policy=LeastPrivilegePolicy(),
    approvals=SQLiteApprovalStore(store),
    idempotency=InMemoryIdempotencyStore(),  # journal receipts supersede this port
    run_store=store, event_store=store, checkpoint_store=store,
    events=InMemoryEventSink(), budget=BudgetLedger(BudgetLimit()),
    context=ContextManager(100_000), journal=store,
)
runner = GovernedAgentRunner(runtime)
try:
    result = await runner.run(llm, objective="Process an approved order",
                              principal=principal, registry=registry)
except RunSuspended as suspended:
    # A trusted reviewer must decide via runtime.approvals.decide(...).
    # Store suspended.run_id, then resume with a fresh runtime if necessary.
    pass
result = await runner.resume(run_id, llm, principal=principal, registry=registry)
```

`resume_stream` has the same persistence and policy semantics as `resume`.
Resumption checks the original tenant and subject, then current permissions.
Model ID, explicit tool versions, schemas and security metadata must match the
recorded manifest. Changing code without incrementing its tool version is outside
the guarantee. API/database formats are versioned and intentionally not migrated
implicitly during beta. Completed/failed runs are not restartable via resume.

## Durable boundaries

Before the first model request: persist objective/configuration and acquire the
execution owner. Before a tool batch: persist the exact assistant message,
arguments and pending invocation IDs. Before each external tool: validate,
authorize, resolve approval, reserve budget, acquire effect locks, and persist a
started receipt. After execution and output validation: persist its result. After
the batch: persist tool-result messages and advance the loop checkpoint. The final
answer is checkpointed before completion is emitted.

A completed invocation is reused without executing its external effect again.
Invocations are identified by run, turn and provider call ID, with a fingerprint
of tool name, declared version and canonical arguments. Two intentional calls
with identical arguments in different turns are distinct.

An invocation with a started receipt but no completed result raises OutcomeUnknown.
The runner enters WAITING with a reconciliation event. It does not ask the model
to retry, even if the tool is labelled idempotent. This conservative rule covers
crashes, uncertain transport failures, timeouts and output-validation failures.

## Ownership and operator reconciliation

A process owns a run until it exits normally. There is no automatic lease expiry.
To recover after a process crash, the operator must first **stop the old worker**,
then call `store.recover_execution(run_id, expected_owner, actor=..., evidence=...)`.
Find its owner using `execution_owner(run_id)`. Recovery changes the owner using a
compare-and-set and records an audit note. A note is not proof of process death;
the embedding application must enforce this operational precondition.

Use `reconcile_action(run_id, call_id, actor=..., evidence=..., result=...)` when an
external system supplies the confirmed result. The result must be the serialized
Lughus tool-result envelope (`{"ok": true, "result": ...}`). Alternatively set
`confirmed_not_executed=True` only when an operator has verified no effect took
place. Blind replay of unknown effects is forbidden. Reconciliation requires the
execution owner to have been released. Only then may `resume` continue.

These are trusted operator APIs, not self-authorizing HTTP endpoints. Enforce
reviewer/operator ACLs and tenant isolation in the application. Do not expose a
raw database or these methods to model-generated tools.

## Explicit constraints

- Use stateless tools with typed arguments. Durable tools cannot accept injected
  mutable `state`; hidden closure state is also outside the recovery contract.
- SQLite stores conversation history and tool outputs as JSON, never pickle.
  Configure filesystem ACLs, encryption, backups and retention for sensitive data.
  A new database is created mode 0600; existing file permissions are not changed.
- One owner per run. Separate runs can execute concurrently on one host. Global
  resource locks remain process-local. No NFS, distributed claims or cross-host
  exclusive-effect guarantees are provided.
- Durable budgets are **per run**, with configured limits copied from runtime.budget.
  Reservations are persisted before dispatch. Recovery conservatively charges
  reservations whose final consumption is unknown. Token usage is observed after
  provider responses, not a guaranteed pre-call token or monetary ceiling.
- Consumer cancellation pauses a durable run (WAITING) and re-raises cancellation.
  It does not pretend an external side effect was rolled back.
- The external system and journal cannot share an atomic transaction. A crash
  between them requires reconciliation or external idempotency. No universal
  exactly-once claim is made.

Tests: `test_sqlite_v021.py` includes a real child-process `os._exit` boundary;
`test_resume_v021.py` exercises public suspend/approve/resume with a new runtime;
`test_functional_v021.py` covers typed inputs and budget settlement.
