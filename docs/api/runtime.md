---
type: API Reference
title: Execution Runtime & Event Stream API
description: API reference for lughus.infra.runtime, lughus.agent.runner, and lughus.core.event_stream modules.
---

# Execution Runtime & Event Stream API

The `lughus.infra.runtime`, `lughus.agent.runner`, and `lughus.core.event_stream` modules manage process-local resource pools, event streaming, and agent execution orchestration.

---

## Classes & Interfaces

### `RuntimeConfig`

```python
@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    max_global_tools: int = 64
    max_sync_workers: int = 32
    queue_timeout: float | None = None
```

Configures thread pool workers and bulkhead concurrency limits for one `ExecutionRuntime`. `queue_timeout` is the default wait applied by `tool_slot()` when no explicit timeout is passed.

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

### `GovernedAgentRunner`

```python
class GovernedAgentRunner:
    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        *,
        event_sink: EventSink | None = None,
    ) -> None: ...

    async def run(
        self,
        llm: Any,
        *,
        objective: str = "",
        principal: Principal | None = None,
        registry: ToolRegistry | None = None,
        state: Any = None,
        context_items: Sequence[ContextItem] = (),
        max_iterations: int = 20,
        system: str = "You are a helpful assistant.",
        context: str = "",
        tool_names: Sequence[str] | None = None,
        thread_id: str | None = None,
    ) -> LoopResult: ...
```

`GovernedAgentRunner` provides event-streamed execution orchestration. Without an `AgentRuntime`, it operates in lightweight event-emission mode; with an `AgentRuntime`, it applies the full governance pipeline (context selection, budget tracking, policy enforcement, approval gates, and state coordination).

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

---

### `RunCoordinator` & `RunUnitOfWork`

```python
class RunCoordinator:
    def __init__(self, store: RunUnitOfWork) -> None:
        """Transactional coordinator with per-run sequence allocation."""

    def next_sequence(self, run_id: str) -> int: ...
    async def start(
        self, objective: str, *, tenant_id: str, principal_id: str,
        context_id: str | None = None,
    ) -> Run: ...
    async def transition(
        self,
        run: Run,
        status: RunStatus,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        pending_action: str | None = None,
        pending_arguments_hash: str | None = None,
        outcome_unknown: bool = False,
    ) -> Run: ...


class RunUnitOfWork(Protocol):
    async def create_transition(
        self, run: Run, event: RunEvent, checkpoint: Checkpoint
    ) -> None: ...
    async def commit_transition(
        self, *, run_id: str, expected_version: int, status: RunStatus,
        event: RunEvent, checkpoint: Checkpoint,
    ) -> Run: ...

Transactional state machine coordinator enforcing valid status transitions (`PENDING`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED`, `CANCELLED`) with per-run sequence allocation and atomic Unit of Work persistence across run records, checkpoints, and event streams.
