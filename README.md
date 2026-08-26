<p align="center">
  <img src="docs/logo.svg" width="360" alt="lughus logo" />
</p>

<p align="center">
  <a href="https://pypi.org/project/lughus/"><img src="https://img.shields.io/pypi/v/lughus.svg?color=blue" alt="PyPI version" /></a>
  <a href="https://pypi.org/project/lughus/"><img src="https://img.shields.io/pypi/pyversions/lughus.svg" alt="Supported Python versions" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# lughus

Micro-framework for building [A2A](https://google.github.io/A2A/) agents with [LiteLLM](https://github.com/BerriAI/litellm). Register tools, run an agentic loop, get a result. No graphs, no runners, no magic.

## Install

```bash
pip install lughus              # Core (litellm, python-dotenv, jsonschema)
pip install lughus[server]      # + FastAPI, uvicorn, a2a-sdk
pip install lughus[all]         # Everything
```

## Quick Start

A complete agent in one script. Register a tool, call `agent_loop`, get the LLM's response:

```python
import asyncio
import json

from lughus import ToolRegistry, agent_loop
from lughus.testing import MockLLM


# 1. Create a tool registry and register a tool
registry = ToolRegistry()


@registry.tool(
    "greet",
    "Greet a user by name.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name to greet"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
def greet(*, name: str, state) -> str:
    return json.dumps({"greeting": f"Hello, {name}!"})


# 2. Create an LLM (MockLLM for offline testing, LLM for production)
llm = MockLLM(
    [
        # Turn 1: LLM calls the greet tool
        [{"name": "greet", "arguments": {"name": "World"}, "id": "call_1"}],
        # Turn 2: LLM produces a text response (ends the loop)
        "Hello, World!",
    ]
)


# 3. Run the agent loop
async def main():
    result = await agent_loop(
        llm,
        system="You are a greeting assistant. Use the greet tool.",
        context="Say hello to World",
        registry=registry,
        tool_names=["greet"],
        state=None,
    )
    print(result)  # "Hello, World!"
    print(f"{result.iterations} iterations, {result.total_tokens} tokens")


asyncio.run(main())
```

For production, swap `MockLLM` for a real LLM:

```python
from lughus import LLM

llm = LLM(model="openai/gpt-4o", max_output_tokens=16384)
```

## Features

- **`agent_loop()`** -- iterates LLM + tools until a text response, with parallel tool execution
- **`agent_loop_stream()`** -- same, but yields text chunks as the LLM generates them
- **`ToolRegistry`** -- `@registry.tool()` decorator for sync and async Python functions
- **`BaseGateway`** -- A2A `AgentExecutor` (message extraction, artifact handling)
- **`LLM`** -- thin wrapper around `litellm.acompletion()`, supports 100+ providers
- **`build_app()` / `serve()`** -- A2A ASGI app + uvicorn in one call
- **Governance** -- deterministic tool policies, scoped permissions, human-in-the-loop approvals
- **Observability** -- native OpenTelemetry traces and metrics on every request

## Configuration

All configuration is via environment variables. Key settings:

| Variable | Default | Description |
|---|---|---|
| `AGENT_MODEL` | *(required)* | LiteLLM model string (e.g. `openai/gpt-4o`) |
| `MAX_OUTPUT_TOKENS` | `16384` | Max output tokens per LLM call |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | Server listen address |
| `LUGHUS_ENV` | `development` | Set `production` for strict startup validation |
| `API_BEARER_TOKEN` | *(not set)* | Bearer token for non-health routes |

Provider routing is automatic via LiteLLM:

```bash
export AGENT_MODEL="openai/gpt-4o"       && export OPENAI_API_KEY="sk-..."
export AGENT_MODEL="anthropic/claude-sonnet-4-20250514" && export ANTHROPIC_API_KEY="sk-ant-..."
export AGENT_MODEL="gemini/gemini-2.5-flash" && export GEMINI_API_KEY="..."
```

## Scaffold a New Agent

```bash
lughus new my_agent
cd my_agent && pip install -e ".[dev]" && pytest -q
python -m my_agent  # starts A2A server on :8080
```

## Governance

Tools can declare risk levels, required scopes, and approval workflows. The policy engine evaluates actions deterministically before execution -- prompt instructions are never used as access controls. See [docs/guides/agentic-design.md](docs/guides/agentic-design.md) for agentic design rules.

```python
from lughus import ToolRegistry, ToolRisk, ToolEffect

registry = ToolRegistry()

@registry.tool(
    "deploy",
    "Deploy to production.",
    {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]},
    risk=ToolRisk.CRITICAL,
    effects=frozenset([ToolEffect.WRITE, ToolEffect.IRREVERSIBLE]),
    requires_approval=True,
)
def deploy(*, service: str, state) -> str:
    return json.dumps({"status": "deployed"})
```

## Links

- [CHANGELOG](CHANGELOG.md)
- [CONTRIBUTING](CONTRIBUTING.md)
- [Architecture decisions](docs/architecture/)
- [Agentic design rules](docs/guides/agentic-design.md)
- [Guarantees](docs/guarantees.md)
- [LiteLLM providers](https://docs.litellm.ai/docs/providers)

## License

MIT -- see [LICENSE](LICENSE).
