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
    async def close(self) -> None: ...
```

Process-local resource manager providing isolated thread pool execution (`run_sync`) and event-loop-bound concurrency semaphores (`tool_slot`).

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
    async def emit(self, event: RunEvent) -> None: ...


class InMemoryEventSink:
    def __init__(self) -> None: ...
    async def emit(self, event: RunEvent) -> None: ...
    def events(self) -> list[RunEvent]: ...
```

Pub/sub event stream interface and reference in-memory implementation enforcing monotonic sequence numbering.
