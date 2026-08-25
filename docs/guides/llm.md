> [← Documentation index](../index.md)

# LLM Configuration

## Generation Parameters

Pass provider-specific parameters via `params`:

```python
from lughus import LLM

llm = LLM("openai/gpt-4o", params={"temperature": 0, "seed": 42})
```

These parameters are forwarded to every `generate()` and `astream()` call. Use `temperature=0` and a fixed `seed` for reproducible runs.

### Reserved keys

The following keys are managed by the framework and cannot be set via `params`:
`messages`, `tools`, `stream`, `stream_options`, `model`.

Attempting to set a reserved key raises `ValueError` at construction time.

## Lazy LiteLLM Loading

LiteLLM is **not imported** when lughus starts. `import litellm` costs several
seconds at cold start (it eagerly wires every provider SDK), so `lughus.engine.llm`
resolves it through an internal memoized accessor the first time an actual API
call is made.

What this means in practice:

- Constructing `LLM(...)`, `BudgetedLLM(...)`, or running tests with `MockLLM`
  never loads litellm.
- The first real `generate()` / `astream()` call triggers the import once
  (~6-7 s on first use, then free).
- Retry handling (`RateLimitError`, `ServiceUnavailableError`,
  `APIConnectionError`) resolves its exception classes lazily too, inside the
  retry loop — no eager import there either.

This keeps CLI tools, test suites and server workers that don't call the LLM
fast to start. If your deployment pre-warms processes (e.g. gunicorn
`--preload`), consider calling `lughus.engine.llm._litellm()` once at boot so
workers don't each pay the import cost on their first request.

**Related:** [Loop API](../api/loop.md) · [Testing Guide](testing.md)
