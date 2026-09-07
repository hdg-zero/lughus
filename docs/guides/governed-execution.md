# Governed execution (0.19)

`GovernedAgentRunner(runtime).run()` and `.stream()` use the same lifecycle.
Both require `objective`, authenticated `principal` and `registry`. The runner
owns the tool configuration: an override cannot disable the runtime policy.
Streaming also enforces approvals, budget accounting and context selection.
`run()` accepts a GenerateLLM; `stream()` accepts a StreamingLLM.

```python
runner = GovernedAgentRunner(runtime)
result = await runner.run(llm, objective="Inspect orders", principal=principal,
                          registry=registry)
async with contextlib.aclosing(runner.stream(
    llm, objective="Inspect orders", principal=principal, registry=registry,
)) as events:
    async for event in events:
        print(event.type, event.data)
```

The producer queue is bounded. Close the iterator when abandoning a response;
use `contextlib.aclosing` on early exit. Cancellation is persisted and propagated.
Text deltas are provisional. They must not be treated as approved final output.
Audit events can contain arguments/results: do not expose them to unauthorised
clients. This runner API is a trusted application interface, not an HTTP ACL.

The supplied runtime and its ledger are application-scoped and caller-owned.
Use separate runtimes/ledgers for separate tenants or independently budgeted runs.
A consumed budget is not automatically reset at the next request.

GLOBAL_EXCLUSIVE now excludes parallel tools too, with writer preference.
Synchronous worker submissions are bounded and preserve contextvars. A timed-out
Python thread cannot be killed: cancellation drains it before releasing effect
locks. Thus synchronous timeouts are cooperative, not a hard latency guarantee.
Use async I/O or the confined interpreter for hard termination requirements.

Events are written as they happen, but 0.19 is not a durable resumption engine.
See the release-specific recovery documentation before assuming crash recovery.
