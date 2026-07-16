# Contributing to lughus

Thank you for your interest in contributing!

---

## Dev setup

```bash
# Clone the repo
git clone https://github.com/your-org/lughus.git
cd lughus

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

---

## Running tests

```bash
# Full test suite
pytest tests/ -v

# Single file
pytest tests/test_tools.py -v

# With coverage report
pytest tests/ --cov=lughus --cov-report=term-missing

# Target: ≥ 85% coverage
```

---

## Type checking

```bash
mypy lughus/
```

The package ships with a `py.typed` marker (PEP 561). All public APIs must be
fully typed. `mypy` must pass with no errors before any PR is merged.

---

## Testing your agent with `MockLLM`

`lughus` exposes `MockLLM` and `MockStreamingLLM` inside the `lughus.testing` module for downstream agent authors to test their agents and workspaces. You can use it in your agent's own tests:

```python
from lughus.testing import MockLLM
from lughus import ToolRegistry, agent_loop

async def test_my_agent():
    llm = MockLLM([
        # First iteration: LLM calls a tool
        [{"id": "c1", "name": "my_tool", "arguments": {"param": "value"}}],
        # Second iteration: LLM returns text
        "Task completed successfully.",
    ])
    registry = ToolRegistry()

    @registry.tool("my_tool", "My tool.", {"type": "object", "properties": {}})
    def my_tool(*, param: str, state) -> str:
        return '{"ok": true}'

    result = await agent_loop(
        llm, system="You are helpful.", context="Do the task",
        registry=registry, tool_names=["my_tool"], state=None,
    )
    assert "completed" in result
```

This module is not imported by default in `lughus/__init__.py` to avoid production overhead. Always import it explicitly. See [docs/guides/testing.md](docs/guides/testing.md) for details.

---

## Code style

- Python 3.11+ syntax
- `from __future__ import annotations` in every file
- Type annotations on all public functions and methods
- Docstrings on all public classes and functions
- No magic — prefer explicit over implicit

---

## Adding a new public API

1. Implement in the appropriate module (`loop/` sub-package, `tools.py`, etc.).
2. Export from `__init__.py` and add to `__all__` if it should be imported from the top-level package, or document the module-level import (e.g. `lughus.testing`).
3. Add to the `API reference` section in `README.md`.
4. Write tests with ≥ 90% branch coverage for the new code.
5. Update `CHANGELOG.md` under `[Unreleased]`.

---

## Documentation Workflow & OKF Guidelines

We prioritize comprehensive, up-to-date documentation. Every design decision and public API change should be documented under the Open Knowledge Format (OKF):

### 1. Architectural & Concept Changes
If your change alters the system's design or introduces new architectural policies (e.g. timeout strategies, retry mechanisms):
- Document the design decisions and architectural guidelines under the appropriate files in `docs/` (using the Open Knowledge Format with YAML frontmatter).
- Add new concept, reference, or guide documents as needed under `docs/overview.md`, `docs/api/`, or `docs/guides/`.

### 2. User-Facing Features & Configuration
If your change adds new configuration settings, environment variables, or CLI parameters:
- Update the **Configuration** table in `README.md`.
- Document any usage instructions in the relevant sections of `README.md`.
- Ensure changes are mentioned in the **Production Checklist** if they affect operational stability or observability.
