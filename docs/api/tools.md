---
type: API Reference
title: Tool Registry API
description: API reference for the ToolRegistry class.
---

> [← Documentation index](../index.md)

# Tool Registry API

The `ToolRegistry` handles registration and declaration extraction for sync/async tools. Runtime execution is handled by the loop module, which applies bounded concurrency and optional per-tool timeouts through `ToolExecutionConfig`.

## Class Definition

```python
class ToolRegistry:
    def __init__(self, tools: Sequence[Callable[..., Any] | ToolDef] | None = None):
```

---

## Methods

### `tool`

Decorator to register a function as a tool. Supports automatic schema inference from type hints and docstrings.

```python
def tool(
    self,
    name_or_fn: str | Callable[..., Any] | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    *,
    output_schema: dict[str, Any] | type[BaseModel] | None = None,
    version: str = "1",
    effects: frozenset[ToolEffect] | None = None,
    risk: ToolRisk = ToolRisk.UNKNOWN,
    required_scopes: frozenset[str] | None = None,
    idempotent: bool = False,
    requires_approval: bool = False,
    concurrency: ConcurrencyMode = ConcurrencyMode.PARALLEL_SAFE,
    resource_key: Callable[[Mapping[str, Any]], str] | None = None,
    timeout: float | None = None,
) -> Any:
```

#### Parameters
*   `name_or_fn`: Optional tool name or callable (when used as a bare decorator `@registry.tool`). Defaults to function `__name__`.
*   `description`: Description explaining when and how to use the tool. Defaults to docstring summary.
*   `parameters`: Optional manual JSON Schema dictionary. If omitted, automatically inferred from type hints via Pydantic `TypeAdapter` and docstrings.
*   `output_schema`: Optional JSON Schema or Pydantic `BaseModel` class validating and serializing tool output values.
*   `version`: Tool version string (default `"1"`).
*   `effects`: Frozenset of `ToolEffect` (`READ`, `WRITE`, `EXTERNAL`, `IRREVERSIBLE`).
*   `risk`: `ToolRisk` level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, `UNKNOWN`).
*   `required_scopes`: Frozenset of required security scopes evaluated by policy engines.
*   `idempotent`: Boolean indicating if repeated execution with identical arguments is side-effect safe.
*   `requires_approval`: Boolean forcing a human approval request before execution.
*   `concurrency`: `ConcurrencyMode` (`PARALLEL_SAFE`, `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, `GLOBAL_EXCLUSIVE`).
*   `resource_key`: Callable extracting a resource identifier from tool arguments (required for `SERIAL_PER_RESOURCE`).
*   `timeout`: Optional per-tool execution timeout overriding global configuration.

Tool names must be unique in one registry. The callable does not need to accept `state` unless it needs agent state; if `state` is present, it is injected automatically without appearing in the LLM tool declaration schema.

#### Example (Pydantic-First DX)
```python
from lughus import ConcurrencyMode, ToolEffect, ToolRegistry, ToolRisk

registry = ToolRegistry()


@registry.tool(
    effects=frozenset([ToolEffect.WRITE, ToolEffect.EXTERNAL]),
    risk=ToolRisk.HIGH,
    required_scopes=frozenset(["finance:transfer"]),
    requires_approval=True,
    concurrency=ConcurrencyMode.SERIAL_PER_TOOL,
)
def transfer_funds(account_id: str, amount: float) -> dict:
    """Transfer funds to an external account.

    Args:
        account_id: Target account identifier.
        amount: Amount to transfer.
    """
    return {"status": "completed", "tx_id": "tx_12345"}
```

Tools may return strings or JSON-serializable Python values. Non-string values are serialized before they are appended to the LLM message history.


### `register`

Registers a pre-defined `@tool`-decorated function or a `ToolDef` instance into the registry.

```python
def register(self, tool_or_fn: Callable[..., Any] | ToolDef) -> ToolDef:
```

### Standalone `@tool` Decorator

Tools can be defined anywhere in your codebase using the standalone `@tool` decorator, without creating a `ToolRegistry` instance in advance.

```python
from lughus import tool, ToolRisk

@tool(risk=ToolRisk.LOW)
def lookup_user(user_id: str) -> dict:
    """Look up a user record by ID.
    
    Args:
        user_id: Unique user identifier.
    """
    return {"user_id": user_id, "name": "Ada Lovelace"}
```

Standalone tools can be passed directly to `agent_loop(tools=[lookup_user])` or registered via `registry.register(lookup_user)`. Decorated functions remain directly callable in standard Python code.

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

---

## Built-in Tools: Code Interpreter

Lughus ships with a fail-closed, container-confined Python execution environment with OCI sandboxing, resource ceilings, approval gating, and binary artifact export:

```python
from lughus import (
    ContainerConfig,
    ContainerPythonBackend,
    FileArtifactStore,
    ToolRegistry,
    register_code_interpreter,
)

registry = ToolRegistry()
backend = ContainerPythonBackend(
    ContainerConfig(
        image="python:3.12-slim@sha256:4b4c730e160a28f4d80a1c6a2e8cfa10bf23bc7155e8ccbe0ffc4c23f2f5abde",
        engine="docker",  # or "podman"
        timeout_s=30.0,
        memory_mb=512,
        cpus=1.0,
    )
)
artifact_store = FileArtifactStore("./artifacts")

# Register canonical "code_interpreter" tool
tool_name = register_code_interpreter(
    registry,
    backend=backend,
    artifact_store=artifact_store,
    requires_approval=True,
)
```

### Signature: `register_code_interpreter`

```python
def register_code_interpreter(
    registry: ToolRegistry,
    *,
    backend: PythonBackend,
    artifact_store: BinaryArtifactStore,
    requires_approval: bool = True,
) -> str:
```

| Parameter | Type | Description |
|---|---|---|
| `registry` | `ToolRegistry` | Target registry where `"code_interpreter"` is registered. |
| `backend` | `PythonBackend` | Backend implementation conforming to `PythonBackend` protocol. |
| `artifact_store` | `BinaryArtifactStore` | Store for indexing binary files produced during script execution. |
| `requires_approval` | `bool` | Whether invocations require governance approval (defaults to `True`). |

**Registered tool characteristics:**
- **Tool Name:** `"code_interpreter"`
- **Risk Level:** `ToolRisk.HIGH`
- **Effects:** `frozenset({ToolEffect.WRITE, ToolEffect.EXTERNAL})`
- **Input Argument:** `code: str`
- **Output Schema:** `{"stdout": str, "stderr": str, "exit_code": int, "truncated": bool, "files": list[dict]}`

### Protocol: `PythonBackend`

Any execution backend can be plugged into `register_code_interpreter` by implementing the `PythonBackend` protocol:

```python
class PythonBackend(Protocol):
    async def execute(self, code: str) -> InterpreterResult: ...
```

### Container Configuration: `ContainerConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `image` | `str` | *(required)* | Immutable image pinned with `@sha256:...` digest. |
| `engine` | `str` | `"docker"` | Container CLI (`"docker"` or `"podman"`). |
| `timeout_s` | `float` | `30.0` | Host-enforced execution deadline in seconds. |
| `memory_mb` | `int` | `256` | RAM ceiling enforced via Linux cgroups. |
| `cpus` | `float` | `1.0` | CPU core quota limit. |
| `pids_limit` | `int` | `64` | Process limit protecting against fork bombs. |
| `workspace_mb` | `int` | `32` | In-memory `tmpfs` scratch workspace size. |
| `max_output_bytes`| `int` | `20_000` | Truncation limit on captured stdout/stderr. |
| `max_artifact_bytes`| `int` | `10_000_000` | Maximum aggregate size of collected output files. |
| `max_files` | `int` | `32` | Maximum count of exported files per run. |

Exported from `lughus` root and `lughus.engine.interpreter`.

---

**Related:** [Sandboxed Execution Guide](../guides/sandboxed-execution.md) · [Confined Python Security](../security/python-execution.md) · [Tools Guide](../guides/tools.md) · [Tools Contract](../contracts/tools.md) · [Policy API](policy.md) · [MCP Integration](../integrations/mcp.md)
