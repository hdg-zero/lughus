---
type: API Reference
title: LLM Client API
description: API reference for the LLM wrapper client.
---

# LLM Client API

The `LLM` class is a thin, asynchronous wrapper around `litellm.acompletion()` that supports per-call timeouts and automatic retries on transient errors.

`agent_loop()` accepts any object matching the `GenerateLLM` protocol (`model` plus async `generate()`), and `agent_loop_stream()` accepts any object matching `StreamingLLM` (`model`, `timeout`, and async `astream()`). This keeps custom clients and `lughus.testing` mocks type-compatible without subclassing `LLM`.

## Class Definition

```python
class LLM:
    def __init__(
        self,
        model: str,
        max_output_tokens: int = 16384,
        timeout: float | None = 120.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_elapsed: float | None = None,
    ):
```

### Constructor Parameters
*   `model`: The LiteLLM model string (e.g. `"openai/gpt-4o"`, `"anthropic/claude-3-5-sonnet-20241022"`). Required.
*   `max_output_tokens`: Maximum tokens in the LLM response (default: `16384`).
*   `timeout`: Timeout in seconds for individual LLM requests. Set to `None` or `0` to disable timeouts.
*   `max_retries`: Number of retries on transient errors (`RateLimitError`, `ServiceUnavailableError`, `APIConnectionError`, and call timeouts). Default: `3`.
*   `retry_base_delay`: Base delay in seconds for exponential backoff between retries. The actual delay uses jitter unless the provider supplies `Retry-After`.
*   `retry_max_elapsed`: Optional total retry sleep budget in seconds. Set to `None` or `0` to disable.

Transient retries emit the `lughus.llm.retries` OpenTelemetry counter. If the provider exposes a `Retry-After` header, that delay is honored before falling back to exponential jitter. When an `LLM` is used through `agent_loop()` or `agent_loop_stream()`, `retry_max_elapsed` is shared across all LLM calls in that loop invocation.

For streaming, retries apply to stream creation. If a provider connection fails
after chunks have already been yielded, Lughus surfaces the error instead of
replaying the stream, because replaying can duplicate emitted text or partial
tool-call arguments.

---

## Methods

### `generate`

Sends messages and optional tools to the LLM.

```python
async def generate(
    self,
    *,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> litellm.ModelResponse:
```

### `astream`

Returns an async iterable yielding streaming delta chunks.

```python
async def astream(
    self,
    *,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> AsyncIterator[litellm.ModelResponse]:
```
