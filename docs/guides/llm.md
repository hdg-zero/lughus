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
