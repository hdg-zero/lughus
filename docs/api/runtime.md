---
type: API Reference
title: Execution Runtime & Event Stream API
description: API reference for lughus.runtime, lughus.runner, and lughus.event_stream modules.
---

# Execution Runtime & Event Stream API

The `lughus.runtime`, `lughus.runner`, and `lughus.event_stream` modules manage process-local resource pools, event streaming, and agent execution orchestration.

---

## Classes & Interfaces

### `RuntimeConfig`

```python
@dataclass(frozen=True)
class RuntimeConfig:
    max_sync_thread_workers: int = 32
    max_global_tools: int = 64
```

Configures process-wide thread pool workers and bulkhead concurrency limits.

---

### `ExecutionRuntime`

```python
class ExecutionRuntime:
    def __init__(self, config: RuntimeConfig | None = None) -> None: ...
    async def run_sync(self, fn: Callable[[], T]) -> T: ...
    def tool_slot(self, timeout: float | None = None) -> AsyncContextManager[None]: ...
    def resource_slot(self, key: str) -> AsyncContextManager[None]: ...
    async def close(self) -> None: ...
```

Process-local resource manager providing isolated thread pool execution (`run_sync`), event-loop-bound concurrency semaphores (`tool_slot`), and resource key locks (`resource_slot`).

---

### `AgentRuntime`

```python
@dataclass(frozen=True, slots=True)
class AgentRuntime:
    execution: ExecutionRuntime
    policy: ToolPolicy
    approvals: ApprovalStore
    idempotency: IdempotencyStore
    run_store: RunStore
    event_store: EventStore
    checkpoint_store: CheckpointStore
    events: EventSink
    budget: BudgetLedger
    context: ContextManager

    def tool_config(self, *, run_id: str, principal: Principal) -> ToolExecutionConfig: ...
```

Composition root bundling process execution, policies, approval stores, idempotency, durability stores, event sinks, budgets, and context managers into a unified governed runtime configuration.

---

### `AgentRunner`

```python
class AgentRunner:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry | None = None,
        runtime: ExecutionRuntime | None = None,
        event_sink: EventSink | None = None,
    ) -> None: ...
```

Orchestrator wrapping agent loop execution and emitting structured domain events (`run.started`, `text.delta`, `run.completed`, `run.failed`).

---

### `EventSink` & `InMemoryEventSink`

```python
class EventSink(Protocol):
    async def append(self, event: RunEvent) -> None: ...


class InMemoryEventSink:
    def __init__(self, max_events: int = 10_000) -> None: ...
    async def append(self, event: RunEvent) -> None: ...
    def snapshot(self, run_id: str | None = None) -> tuple[RunEvent, ...]: ...
    async def subscribe(
        self, after_sequence: int = -1, *, run_id: str | None = None
    ) -> AsyncIterator[RunEvent]: ...
```

Pub/sub event stream interface and reference in-memory implementation enforcing monotonic per-run sequence numbering and supporting multi-run global cursor subscriptions via an incremental global offset.
