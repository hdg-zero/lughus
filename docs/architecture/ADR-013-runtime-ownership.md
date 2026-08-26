# ADR-013: Configuration is inert; the loop owns the execution runtime

- **Status:** Accepted
- **Date:** 2026-08-17
- **Relates to:** ADR-003 "Runtime"

## Context

`ToolExecutionConfig.__post_init__` instantiated an `ExecutionRuntime`, and
therefore a `ThreadPoolExecutor` of 32 threads, whenever the field was left at its
default. Nothing ever closed it: `grep -rn 'close(' lughus/loop/` returned
nothing. Three code paths created implicit runtimes -- `__post_init__`,
`_ensure_config` in `_loop.py`, and `cfg = config or ToolExecutionConfig()` in
`_execute.py`. A server handling *N* requests accumulated *N* thread pools.

A second, quieter defect followed from the same design: the implicit runtime was
built with `ExecutionRuntime()` and no argument, so `max_global_tools`,
`max_sync_thread_workers` and `tool_queue_timeout` declared on
`ToolExecutionConfig` had no effect at all. The defaults coincide on both sides
(64/32), which made it invisible except to the user who customises -- that is, the
user with a load problem to solve.

## Decision

**A configuration object never allocates a system resource.** This is now a
project rule (R5 in `CONTRIBUTING.md`), not just a local fix.

- `ToolExecutionConfig.runtime` stays `None` unless the caller injects one. The
  field's positive-value validation is unchanged.
- `agent_loop` and `agent_loop_stream` call `_resolve_tool_config()`, which
  returns `(config, runtime_to_close)`. The loop body runs inside `try/finally`
  and closes **only** the runtime it created. An injected runtime is never closed:
  it belongs to the caller.
- The implicit runtime is derived from the configuration, so the three declared
  limits finally apply.
- `_execute_tools` *requires* a runtime and raises an actionable `RuntimeError`
  when it is absent. A missing runtime is a programming error, not an opportunity
  to leak one.
- When a runtime is injected *and* the configuration declares conflicting
  capacities, `__post_init__` raises `ValueError` naming both values. A built
  runtime cannot be reconfigured, and ignoring the conflict silently is the very
  defect being fixed.

## Alternatives rejected

**A global cache of runtimes keyed by configuration.** This is the origin of the
problem: a subtle cache key, a guaranteed leak, untestable, and accidental sharing
between tenants.

**A module-level singleton.** Forbidden: a runtime is bound to one event loop
(`ExecutionRuntime._bind`). It would break every multi-loop use, including test
harnesses.

**Closing in `__del__`.** Non-deterministic, and `close()` is a coroutine.

**Dropping the capacity fields from `ToolExecutionConfig` entirely** and keeping
them only on `RuntimeConfig`. Conceptually cleaner -- capacity belongs to the
runtime, not to the tool-execution policy -- but it forces any user who wants to
tune concurrency to construct and manage an `ExecutionRuntime`, which makes the
simple case heavier. Both surfaces are kept, with a single junction and a detected
conflict. Flagged for re-examination once there is usage data.

## Consequences

- Constructing a `ToolExecutionConfig` allocates nothing, so it can be built,
  copied and compared freely -- which is what a value type is for.
- A short-lived `agent_loop` now pays thread-pool creation per call (sub-
  millisecond, quantified in `BENCHMARKS.md`). **Servers should create one
  `ExecutionRuntime` at startup, inject it, and close it at shutdown.** See
  `docs/guides/production.md`.
- `cfg.runtime` is non-`None` by contract from `_execute_tools` onwards, so two
  `# type: ignore[union-attr]` markers and one redundant `if cfg.runtime is not
  None` guard were **removed** rather than moved, behind a single `_runtime_of()`
  accessor.
- `agent_loop_stream` is an async generator, so its `finally` runs when the
  generator is exhausted or closed. Consumers that abandon iteration early must
  close it (`contextlib.aclosing`). Documented in `docs/contracts/streaming.md`
  and asserted by the streaming contract suite.

## Enforcement

`tests/test_runtime_ownership.py` validates thread pool cleanup:
`test_repeated_loops_do_not_leak_threads` (verifies thread count returns to baseline after repeated loops) and `test_config_limits_reach_the_implicit_runtime`.
