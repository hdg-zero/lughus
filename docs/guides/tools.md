> [← Documentation index](../index.md)

# Tool Concurrency Modes

Lughus tools declare a `ConcurrencyMode` that controls how the runtime schedules concurrent invocations.

| Mode | Lock scope | Use case | `resource_key` required? |
|:---|:---|:---|:---|
| `PARALLEL_SAFE` | None | Stateless / read-only tools (default) | No |
| `SERIAL_PER_TOOL` | One lock per tool name | Tools with internal mutable state | No |
| `SERIAL_PER_RESOURCE` | One lock per `tool:resource_key(args)` | Tools that mutate a named external resource | Yes |
| `GLOBAL_EXCLUSIVE` | Single process-wide lock | Operations that must not overlap with anything | No |

## Choosing a mode

* Start with `PARALLEL_SAFE` (the default). Most tools that read data or call idempotent APIs need no serialization.
* Use `SERIAL_PER_TOOL` when a tool maintains in-process state that is not safe to mutate concurrently (e.g. an append-only log writer).
* Use `SERIAL_PER_RESOURCE` when concurrent calls are safe as long as they target different resources. Provide a `resource_key` callable that extracts the resource identifier from the tool arguments.
* Reserve `GLOBAL_EXCLUSIVE` for operations that must run in complete isolation, such as schema migrations or global configuration changes.

## Registration-time validation

`SERIAL_PER_RESOURCE` requires a `resource_key` callable at registration. Omitting it raises `ToolValidationError` immediately, so misconfiguration is caught before the first agent loop runs.

```python
from lughus import ConcurrencyMode, ToolRegistry

registry = ToolRegistry()

@registry.tool(
    "update_record",
    "Update a record by ID.",
    {
        "type": "object",
        "properties": {"record_id": {"type": "string"}, "value": {"type": "string"}},
        "required": ["record_id", "value"],
    },
    concurrency=ConcurrencyMode.SERIAL_PER_RESOURCE,
    resource_key=lambda args: args["record_id"],
)
async def update_record(*, record_id: str, value: str, state) -> str:
    ...
```

---

**Related:** [Tools API](../api/tools.md) · [Tools Contract](../contracts/tools.md)
