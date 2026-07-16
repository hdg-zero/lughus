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
) -> Callable:
```

#### Parameters
*   `name`: Name of the tool as exposed to the LLM.
*   `description`: Description explaining when and how to use the tool.
*   `parameters`: JSON Schema dictionary defining the tool parameters. The schema is validated at registration time and invalid schemas raise `ToolValidationError`.

Tool names must be unique in one registry. The callable must accept `state=...` as a keyword argument or through `**kwargs`; this catches signature mistakes when the tool is registered instead of during an LLM run. Positional-only parameters are rejected, and schema properties must match keyword-callable parameters unless the function accepts `**kwargs`.

#### Example
```python
registry = ToolRegistry()

@registry.tool(
    name="add",
    description="Add two numbers.",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
    }
)
def add(*, a: int, b: int, state) -> dict:
    return {"result": a + b}
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
    compact: bool = False,
) -> list[dict]:
```

#### Parameters
*   `names`: Names of tools to extract declarations for. If a name is unknown, a `WARNING` is logged and it is skipped.
*   `strict`: If `True`, unknown names raise `ToolValidationError`. `agent_loop()` uses strict declarations so misconfigured `tool_names` fail before the first LLM request.
*   `compact`: If `True`, parameter descriptions are stripped from the schemas to reduce repeated prompt tokens.

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
