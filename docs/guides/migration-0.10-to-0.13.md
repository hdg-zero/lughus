# Migration guide: lughus 0.10.x to 0.13.0

This guide covers all breaking changes introduced in lughus 0.11.0, 0.12.0,
and 0.13.0. Changes are ordered by impact frequency -- start from the top and
work down.

---

## 1. Streaming API (affects all stream consumers)

`agent_loop_stream()` now yields `StreamChunk` objects for provisional content
and a single `LoopResult` at the end, instead of yielding raw strings.

**Before (0.10.x):**

```python
async for chunk in agent_loop_stream(llm, system=system, context=ctx,
                                     registry=registry, tool_names=names):
    print(chunk, end="")  # chunk was a plain str
```

**After (0.13.0):**

```python
from lughus import StreamChunk, LoopResult

async for item in agent_loop_stream(llm, system=system, context=ctx,
                                    registry=registry, tool_names=names):
    if isinstance(item, StreamChunk):
        print(item.content, end="")        # provisional text fragment
    elif isinstance(item, LoopResult):
        print(f"\nDone in {item.iterations} iterations")
```

`StreamChunk` is a frozen dataclass with two fields: `content: str` and
`final: bool` (always `False` for chunks; `LoopResult` is the final value).
You can also branch on the `final` attribute instead of `isinstance`:

```python
async for item in agent_loop_stream(...):
    if not item.final:
        print(item.content, end="")
```

**Removed:** `StreamingMode.LIVE_AT_MOST_ONCE` no longer exists. The only
valid streaming modes are `StreamingMode.BUFFERED` (default) and
`StreamingMode.LIVE`.

---

## 2. Tool result format (affects tool result consumers)

Tool outputs are now wrapped in a JSON envelope. If your code reads raw tool
results from event streams or from the message history, update the parsing.

**Success envelope:**

```json
{"ok": true, "result": "<tool output, parsed as JSON if valid>"}
```

When the output was truncated:

```json
{"ok": true, "result": "...", "truncated": true, "original_bytes": 12345}
```

**Error envelope:**

```json
{
  "ok": false,
  "error": "ToolTimeoutError",
  "message": "Tool 'search' timed out after 30.0s",
  "retryable": true,
  "fix": "Retry with simpler input or increase timeout"
}
```

If you previously inspected tool result strings directly, parse the envelope:

```python
import json

result = json.loads(tool_output)
if result["ok"]:
    value = result["result"]
else:
    error_msg = result["message"]
    can_retry = result["retryable"]
```

Tool *authors* do not need to change anything -- the framework wraps outputs
automatically. This only affects code that reads tool results from the message
history or event stream after execution.

---

## 3. Runner unification (affects AgentRunner / GovernedAgentRunner users)

`AgentRunner` and `GovernedAgentRunner` have been merged into a single class.
`AgentRunner` is now an alias for `GovernedAgentRunner`.

**If you used `GovernedAgentRunner`:** no change needed.

**If you used `AgentRunner`:** it still works -- the import and constructor are
unchanged. The class now supports optional governance when you pass a runtime:

```python
from lughus import AgentRunner  # works, same as GovernedAgentRunner

# Ungoverned (identical to old AgentRunner behaviour)
runner = AgentRunner()
result = await runner.run(llm, system="...", context="...",
                          registry=registry, tool_names=["echo"])

# Governed (pass a runtime to enable governance)
runner = AgentRunner(runtime=my_runtime)
result = await runner.run(llm, objective="...", principal=principal,
                          registry=registry)
```

---

## 4. Configuration changes

### Removed options

| Removed | Replacement | Version |
|---|---|---|
| `compact_tool_schemas` | Always compacted (no option) | 0.12.0 |
| `max_message_history_chars` | `max_context_tokens` (token-based) | 0.12.0 |
| `max_global_tools` on `ToolExecutionConfig` | Module-level constant (runtime capacity) | 0.11.0 |
| `max_sync_thread_workers` on `ToolExecutionConfig` | Module-level constant (runtime capacity) | 0.11.0 |

**Before (0.10.x):**

```python
from lughus import ToolExecutionConfig

cfg = ToolExecutionConfig(
    compact_tool_schemas=True,
    max_message_history_chars=200_000,
)
```

**After (0.13.0):**

```python
from lughus import ToolExecutionConfig

cfg = ToolExecutionConfig(
    max_context_tokens=8_192,  # replaces character counting
)
```

### Tightened defaults

Several defaults were tightened in 0.11.0. If your code relied on the old
values, set them explicitly:

| Parameter | Old default | New default |
|---|---|---|
| `max_iterations` | 50 | 12 |
| `max_parallel_tools` | 8 | 4 |
| `tool_timeout` | `None` (unlimited) | `30.0` (seconds) |
| `max_tool_output_chars` | 20,000 | 8,192 |

```python
# To restore 0.10.x behaviour explicitly:
cfg = ToolExecutionConfig(
    max_parallel_tools=8,
    tool_timeout=None,
    max_tool_output_chars=20_000,
)
```

### Runtime ownership

`ToolExecutionConfig` no longer allocates an `ExecutionRuntime` (and its
thread pool) in `__post_init__`. The config is now inert. `agent_loop()` and
`agent_loop_stream()` create and close the runtime automatically. To share a
single thread pool across runs, inject a runtime explicitly:

```python
from lughus import ExecutionRuntime, RuntimeConfig, ToolExecutionConfig

runtime = ExecutionRuntime(RuntimeConfig())
try:
    cfg = ToolExecutionConfig(runtime=runtime)
    result = await agent_loop(llm, tool_config=cfg, ...)
finally:
    await runtime.close()
```

---

## 5. OTel attribute renames

Span attributes now follow the OpenTelemetry GenAI semantic conventions more
closely. Tool-specific attributes moved under the `lughus.*` prefix.

| Old attribute | New attribute |
|---|---|
| `gen_ai.usage.prompt_tokens` | `gen_ai.usage.input_tokens` |
| `gen_ai.usage.completion_tokens` | `gen_ai.usage.output_tokens` |
| `tool.name` | `lughus.tool.name` |
| `tool.timeout_s` | `lughus.tool.timeout_s` |
| `tool.idempotent_hit` | `lughus.tool.idempotent_hit` |

New cache-related attributes added:

- `gen_ai.usage.cached_tokens`
- `gen_ai.usage.cache_read_input_tokens`
- `gen_ai.usage.cache_creation_input_tokens`

If you have dashboards or alerts querying `gen_ai.usage.prompt_tokens` or
`gen_ai.usage.completion_tokens`, update the attribute names. All attributes
now live under either `gen_ai.*` or `lughus.*` -- no bare namespace attributes
are emitted.

---

## 6. New exceptions

These exceptions are new in 0.11.0+ and may be raised where older versions
raised `ToolExecutionError` or generic exceptions:

| Exception | When raised |
|---|---|
| `ApprovalRequired` | A tool requires human approval before dispatch |
| `ApprovalRequiredGroup` | Multiple tools in one turn require approval |
| `RunSuspended` | A governed run is suspended waiting for approvals |
| `ContextBudgetExceeded` | A single atomic message group exceeds the context token budget |

`ApprovalRequired` and its group variant derive from `LughusError`, not
`ToolExecutionError`. They are invisible to the model -- the governed runner
transitions to `WAITING` and raises `RunSuspended` to the caller.

```python
from lughus import RunSuspended, ContextBudgetExceeded

try:
    result = await runner.run(llm, ...)
except RunSuspended as e:
    print(f"Run {e.run_id} paused, {len(e.pending_requests)} approval(s) pending")
    # Present approval requests to human, then resume
except ContextBudgetExceeded:
    print("Message group too large for the context budget")
```

---

## 7. Retry layer simplified

The dual retry mechanism (stream-level + LLM-level) was replaced by a single
LLM-level retry via `retry_max_elapsed=60s`. Mid-stream errors now propagate
immediately instead of being silently retried.

If your code caught stream retry exceptions, update:

```python
# No change needed in most cases. Errors propagate as LughusError
# subclasses. Set retry_max_elapsed on the LLM if you need to tune:
llm = LLM(model="gpt-4", retry_max_elapsed=120)  # seconds
```

---

## 8. New features (non-breaking, for awareness)

These features are opt-in and do not require changes to existing code:

- **Artifact projection** -- large tool outputs stored as artifacts with a
  short reference and summary in history. Enable with
  `ToolExecutionConfig(artifact_projection=True)`. A built-in `fetch_artifact`
  tool is registered automatically.

- **Token-based context budget** -- `max_context_tokens` replaces character
  counting. Oldest atomic message groups are pruned automatically. A
  tool_call/tool_result pair is never split during pruning.

- **Incremental history** -- `MessageHistory` extends messages in place with a
  read-only view, eliminating O(n^2) allocation growth. Internal optimization;
  no API change.

- **Prefix stability for provider caching** -- byte-identical message prefix
  guaranteed across turns so LLM providers can cache effectively. System
  prompt, context items, and user objective form the stable prefix.

- **Precalculated frozen tool declarations** -- `ToolRegistry.declarations()`
  returns memoized, frozen tuples. `deepcopy` removed internally.

- **ConcurrencyMode enum** -- `PARALLEL_SAFE` (new default),
  `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, `GLOBAL_EXCLUSIVE` for explicit
  tool concurrency control.

- **Generation parameters** -- `LLM(params={"temperature": 0.2})` spreads
  user-supplied parameters into provider calls.

---

## Symptom guide

Common errors you may encounter when upgrading, and how to fix them.

### `AttributeError: 'StreamChunk' object has no attribute 'upper'` (or any str method)

**Cause:** Code treats the yielded value as a plain string.

**Fix:** Access `.content` on `StreamChunk` objects:

```python
# Before
async for chunk in agent_loop_stream(...):
    text = chunk.upper()

# After
async for item in agent_loop_stream(...):
    if isinstance(item, StreamChunk):
        text = item.content.upper()
```

### `TypeError: 'ToolExecutionConfig' got an unexpected keyword argument 'compact_tool_schemas'`

**Cause:** The `compact_tool_schemas` option was removed in 0.12.0.

**Fix:** Remove the argument. Tool schemas are always compacted.

```python
# Before
cfg = ToolExecutionConfig(compact_tool_schemas=True)

# After
cfg = ToolExecutionConfig()
```

### `TypeError: 'ToolExecutionConfig' got an unexpected keyword argument 'max_message_history_chars'`

**Cause:** Replaced by `max_context_tokens` in 0.12.0.

**Fix:** Use the token-based parameter instead:

```python
# Before
cfg = ToolExecutionConfig(max_message_history_chars=200_000)

# After
cfg = ToolExecutionConfig(max_context_tokens=8_192)
```

### `ValueError: streaming_mode must be 'buffered' or 'live'`

**Cause:** `StreamingMode.LIVE_AT_MOST_ONCE` was removed.

**Fix:** Use `StreamingMode.LIVE` or `StreamingMode.BUFFERED`:

```python
from lughus.loop import StreamingMode

# Before
async for chunk in agent_loop_stream(..., streaming_mode=StreamingMode.LIVE_AT_MOST_ONCE):
    ...

# After
async for item in agent_loop_stream(..., streaming_mode=StreamingMode.LIVE):
    ...
```

### `TypeError: 'ToolExecutionConfig' got an unexpected keyword argument 'max_global_tools'`

**Cause:** `max_global_tools` and `max_sync_thread_workers` were moved out of
`ToolExecutionConfig` in 0.11.0. They are runtime-level constants.

**Fix:** Remove from `ToolExecutionConfig`. If you need to customize them,
create an `ExecutionRuntime` with the desired `RuntimeConfig`:

```python
# Before
cfg = ToolExecutionConfig(max_global_tools=128, max_sync_thread_workers=16)

# After
from lughus import ExecutionRuntime, RuntimeConfig

runtime = ExecutionRuntime(RuntimeConfig(
    max_global_tools=128,
    max_sync_workers=16,
))
cfg = ToolExecutionConfig(runtime=runtime)
```

### `lughus.errors.ContextBudgetExceeded`

**Cause:** A single tool_call + tool_result group exceeds the entire
`max_context_tokens` budget. This exception is new in 0.12.0.

**Fix:** Increase `max_context_tokens` or reduce tool output size via
`max_tool_output_chars`:

```python
cfg = ToolExecutionConfig(
    max_context_tokens=16_384,
    max_tool_output_chars=4_096,
)
```

### `lughus.errors.RunSuspended`

**Cause:** A governed run encountered a tool that requires human approval. New
in 0.11.0.

**Fix:** Catch `RunSuspended` and present the pending approvals to a human
operator:

```python
from lughus import RunSuspended

try:
    result = await runner.run(llm, ...)
except RunSuspended as e:
    for req in e.pending_requests:
        print(f"Approve {req.tool_name}? (request_id={req.request_id})")
```

### Tools timing out unexpectedly

**Cause:** `tool_timeout` default changed from `None` (unlimited) to `30.0`
seconds in 0.11.0.

**Fix:** Set a higher timeout or disable it:

```python
cfg = ToolExecutionConfig(tool_timeout=120.0)   # 2 minutes
# or
cfg = ToolExecutionConfig(tool_timeout=None)     # unlimited (0.10.x behaviour)
```

### Agent loop hitting iteration limit sooner

**Cause:** `max_iterations` default changed from 50 to 12 in 0.11.0.

**Fix:** Set it explicitly:

```python
result = await agent_loop(llm, max_iterations=50, ...)
```

### OTel dashboards showing no data for token metrics

**Cause:** Attribute names changed from `gen_ai.usage.prompt_tokens` /
`gen_ai.usage.completion_tokens` to `gen_ai.usage.input_tokens` /
`gen_ai.usage.output_tokens`.

**Fix:** Update your dashboard queries and alert rules to use the new
attribute names.
