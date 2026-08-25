---
type: Guide
title: Retry Budget & Reliability
description: How lughus retries transient LLM errors and how to tune the retry budget.
---

> [← Documentation index](../index.md)

# Retry Budget & Reliability

Lughus retries transient LLM errors (rate limits, connection failures, timeouts)
with a **single retry layer** inside `LLM._with_retry()`. This page explains the
knobs you can turn and the invariants the framework guarantees.

## Architecture: one retry layer

```
agent_loop / agent_loop_stream
  |
  +-- llm.generate()  or  llm.astream()
        |
        +-- _with_retry()          <-- single retry envelope
              |
              +-- litellm.acompletion()   (connection to provider)
```

All retry decisions live in `LLM._with_retry()`. The agent loop does **not**
add its own retry. This prevents the retry count from being multiplied across
layers (a `max_retries=3` setting means at most 4 total attempts, not 16).

## Retryable errors

The following exception types are considered transient and trigger a retry:

| Exception | Typical cause |
|---|---|
| `litellm.RateLimitError` | Provider 429 response |
| `litellm.ServiceUnavailableError` | Provider 503 response |
| `litellm.APIConnectionError` | Network failure / DNS error |
| `TimeoutError` | LLM call exceeded `LLM_TIMEOUT` |
| `LLMResponseError` | Provider returned an empty `choices` array |

All other errors (e.g. `BadRequestError`, `AuthenticationError`) are
propagated immediately without retry.

## Configuration

| Env var | `LLM` param | Default | Description |
|---|---|---|---|
| `LLM_MAX_RETRIES` | `max_retries` | `3` | Max retry attempts per call |
| `LLM_RETRY_BASE_DELAY` | `retry_base_delay` | `1.0` s | Base for exponential backoff |
| `LLM_RETRY_MAX_ELAPSED` | `retry_max_elapsed` | `60.0` s | Total retry sleep budget |
| `LLM_TIMEOUT` | `timeout` | `120.0` s | Per-call timeout (each attempt) |

### max_retries

The maximum number of retry attempts after the initial call. With
`max_retries=3`, a persistently failing call makes 4 total attempts
(1 initial + 3 retries). Set to `0` to disable retries entirely.

### retry_base_delay

The base delay in seconds for exponential backoff with jitter. The delay
before attempt N (0-indexed) is a random value in `[0, retry_base_delay * 2^N]`.
Set to `0.0` in test environments to avoid sleeping.

If the provider returns a `Retry-After` header, that value overrides the
computed delay.

### retry_max_elapsed (the budget)

A global cap on the **total time spent sleeping** for retries. Once the
accumulated retry sleep reaches this budget, the next retryable error is
propagated instead of retried, even if `max_retries` has not been exhausted.

The budget is especially useful in streaming agent loops where multiple
LLM calls share one budget via `retry_budget()`:

```python
from lughus.engine.llm import retry_budget

with retry_budget(max_elapsed=30.0):
    # All LLM calls inside this block share a 30-second retry budget.
    # If the first call burns 20s on retries, the second call only
    # has 10s left before errors propagate.
    result = await llm.generate(messages=messages)
```

The agent loop sets up a `retry_budget()` context automatically using
`llm.retry_max_elapsed`.

## Streaming: no retry after first chunk

For streaming calls (`llm.astream()`), retries happen at the **connection
level** -- i.e. when establishing the stream with the provider. Once the
first chunk has been yielded to the consumer, a retry would produce
incoherent text (the consumer already has partial content), so mid-stream
errors **propagate** instead of retrying.

```
astream() call
  |
  +-- _with_retry() establishes the stream   <-- retries here
  |
  +-- async for chunk in stream:             <-- errors propagate here
        yield chunk to consumer
```

## Example: production configuration

```bash
# .env
AGENT_MODEL=openai/gpt-4o
LLM_MAX_RETRIES=3
LLM_RETRY_BASE_DELAY=1.0
LLM_RETRY_MAX_ELAPSED=60
LLM_TIMEOUT=120
```

## Example: test configuration

```bash
# .env.test or monkeypatch in pytest
LLM_MAX_RETRIES=0          # no retries in unit tests
LLM_RETRY_BASE_DELAY=0.0   # no sleeping
LLM_RETRY_MAX_ELAPSED=0    # budget disabled
LLM_TIMEOUT=5              # fast failure
```

## Disabling retries

Set `LLM_MAX_RETRIES=0` to disable retries entirely. Each LLM call will
be attempted exactly once. This is recommended for:

- Unit tests (combine with `LLM_RETRY_BASE_DELAY=0.0`)
- Debugging (to surface errors immediately)
- Environments where the caller manages retries externally

---

**Related:** [Budgets Guide](budget.md) · [Operations: Recovery](../operations/recovery.md) · [ADR-013 — Runtime Ownership](../architecture/ADR-013-runtime-ownership.md)
