---
type: API Reference
title: Tool Registry API
description: API reference for the ToolRegistry class.
---

# Tool Registry API

The `ToolRegistry` handles registration and declaration extraction for sync/async tools. Runtime execution is handled by the loop module, which applies bounded concurrency and optional per-tool timeouts through `ToolExecutionConfig`.

## Class Definition

```python
class ToolRegistry:
    def __init__(self):
```

---

## Methods

### `tool`

Decorator to register a function as a tool.

```python
def tool(
    self,
    name: str,
    description: str,
    parameters: dict,
    *,
    output_schema: dict | None = None,
    version: str = "1",
    effects: frozenset[ToolEffect] | None = None,
    risk: ToolRisk = ToolRisk.UNKNOWN,
    required_scopes: frozenset[str] | None = None,
    idempotent: bool = False,
    requires_approval: bool = False,
    concurrency: ConcurrencyMode = ConcurrencyMode.PARALLEL_SAFE,
) -> Callable:
```

#### Parameters
*   `name`: Name of the tool as exposed to the LLM.
*   `description`: Description explaining when and how to use the tool.
*   `parameters`: JSON Schema dictionary defining the tool parameters. The schema is validated at registration time and invalid schemas raise `ToolValidationError`.
*   `output_schema`: Optional JSON Schema validating tool output values before re-injection into the LLM context.
*   `version`: Tool version string (default `"1"`).
*   `effects`: Frozenset of `ToolEffect` (`READ`, `WRITE`, `EXTERNAL`, `IRREVERSIBLE`).
*   `risk`: `ToolRisk` level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, `UNKNOWN`).
*   `required_scopes`: Frozenset of required security scopes evaluated by policy engines.
*   `idempotent`: Boolean indicating if repeated execution with identical arguments is side-effect safe.
*   `requires_approval`: Boolean forcing a human approval request before execution.
*   `concurrency`: `ConcurrencyMode` (`PARALLEL_SAFE`, `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, `GLOBAL_EXCLUSIVE`).

Tool names must be unique in one registry. The callable must accept `state=...` as a keyword argument or through `**kwargs`; this catches signature mistakes when the tool is registered instead of during an LLM run. Positional-only parameters are rejected, and schema properties must match keyword-callable parameters unless the function accepts `**kwargs`.

#### Example
```python
from lughus import ConcurrencyMode, ToolEffect, ToolRegistry, ToolRisk

registry = ToolRegistry()


@registry.tool(
    name="transfer_funds",
    description="Transfer funds to an external account.",
    parameters={
        "type": "object",
        "properties": {
            "account_id": {"type": "string"},
            "amount": {"type": "number"},
        },
        "required": ["account_id", "amount"],
    },
    output_schema={
        "type": "object",
        "properties": {"status": {"type": "string"}, "tx_id": {"type": "string"}},
        "required": ["status", "tx_id"],
    },
    effects=frozenset([ToolEffect.WRITE, ToolEffect.EXTERNAL]),
    risk=ToolRisk.HIGH,
    required_scopes=frozenset(["finance:transfer"]),
    requires_approval=True,
    concurrency=ConcurrencyMode.SERIAL_PER_TOOL,
)
def transfer_funds(*, account_id: str, amount: float, state) -> dict:
    return {"status": "completed", "tx_id": "tx_12345"}
```

Tools may return strings or JSON-serializable Python values. Non-string values are serialized before they are appended to the LLM message history.


### `declarations`

Generates OpenAI-format tool declarations list for the LLM.

```python
def declarations(
    self,
    names: list[str],
    *,
    strict: bool = False,
) -> tuple[dict, ...]:
```

#### Parameters
*   `names`: Names of tools to extract declarations for. If a name is unknown, a `WARNING` is logged and it is skipped.
*   `strict`: If `True`, unknown names raise `ToolValidationError`. `agent_loop()` uses strict declarations so misconfigured `tool_names` fail before the first LLM request.

The result is memoized and structurally immutable (`tuple` of frozen dicts). Parameter descriptions are preserved — they carry critical constraints (enum values, valid formats, value ranges) that the model needs for accurate tool calls. With prefix caching, tool declarations live in the cacheable prefix so the token cost is negligible.

### `get_fn`

Retrieves the Python callable for a tool by name.

```python
def get_fn(self, name: str) -> Callable | None:
```

### `get_tool`

Retrieves the full tool definition by name.

```python
def get_tool(self, name: str) -> ToolDef | None:
```
