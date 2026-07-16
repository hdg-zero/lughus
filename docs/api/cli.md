---
type: Reference
title: CLI
description: Command line tools for creating lughus agent projects.
---

# CLI

`lughus` ships with a small command line interface focused on project creation.

## `lughus new`

Create a complete agent project:

```bash
lughus new agent_test
```

The command creates:

- `pyproject.toml` with runtime and test dependencies
- `.env.example` with production-oriented defaults
- a Python package matching the agent name
- `config.py` extending `BaseSettings`
- `tools.py` with a JSON-Schema-validated example tool
- `workspace.py` with `agent_loop()` orchestration
- `gateway.py` using `BaseGateway`
- `task_store.py` as the production persistence hook
- `__main__.py` exposing both an ASGI `app` and a local `main()`
- `tests/test_workspace.py` using `MockLLM`

Then run:

```bash
cd agent_test
python -m pip install -e ".[dev]"
pytest -q
python -m agent_test
```

## Options

```bash
lughus new agent_test \
  --display-name "agent-test" \
  --description "Agent test." \
  --skill-id greet \
  --skill-name Greet
```

Use `--dir` to choose a target directory:

```bash
lughus new agent_test --dir ./services/agent_test
```

Use `--interactive` to answer prompts for display metadata:

```bash
lughus new agent_test --interactive
```

The command refuses to write into a non-empty directory.
