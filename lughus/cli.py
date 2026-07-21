"""Command line interface for lughus."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _package_name(value: str) -> str:
    name = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not name:
        raise ValueError("Agent name must contain at least one letter or digit")
    if name[0].isdigit():
        name = f"agent_{name}"
    return name


def _class_prefix(package_name: str) -> str:
    return "".join(part.capitalize() for part in package_name.split("_"))


def _display_name(package_name: str) -> str:
    return package_name.replace("_", "-")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pyproject(project_name: str, package_name: str) -> str:
    return f"""[project]
name = "{project_name}"
version = "0.1.0"
description = "A lughus agent."
requires-python = ">=3.11"
dependencies = [
    "lughus",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["{package_name}*"]

[project.scripts]
{package_name} = "{package_name}.__main__:main"
"""


def _readme(project_name: str, package_name: str, display_name: str) -> str:
    return f"""# {display_name}

A lughus agent scaffold generated with:

```bash
lughus new {project_name}
```

## Install

```bash
python -m pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
export AGENT_MODEL="openai/gpt-4o"
export OPENAI_API_KEY="sk-..."
```

## Test

```bash
pytest -q
```

The default test uses `lughus.testing.MockLLM`, so it does not call a real LLM provider.

## Run

```bash
python -m {package_name}
# or
{package_name}
```

The agent exposes:

- `POST /` — A2A JSON-RPC endpoint
- `GET /.well-known/agent-card.json`
- `GET /health`
- `GET /healthz`
"""


def _env_example() -> str:
    import os
    from dataclasses import fields
    from lughus.config import BaseSettings

    # Temporarily isolate environment variables to get true defaults
    old_env = dict(os.environ)
    os.environ.clear()
    try:
        settings = BaseSettings()
    finally:
        os.environ.update(old_env)

    lines = [
        "AGENT_MODEL=openai/gpt-4o",
        "OPENAI_API_KEY=sk-...",
    ]

    custom_names = {
        "environment": "LUGHUS_ENV",
    }

    for f in fields(BaseSettings):
        if f.name == "model":
            continue
        env_name = custom_names.get(f.name, f.name.upper())
        val = getattr(settings, f.name)
        if val is None:
            val = ""
        elif isinstance(val, bool):
            val = str(val).lower()
        lines.append(f"{env_name}={val}")

    return "\n".join(lines) + "\n"


def _config() -> str:
    return '''"""Agent settings."""
from __future__ import annotations

from dataclasses import dataclass

from lughus import BaseSettings


@dataclass(frozen=True)
class Settings(BaseSettings):
    """Extend BaseSettings with agent-specific configuration when needed."""
'''


def _tools() -> str:
    return '''"""Agent tools."""
from __future__ import annotations

import json
from dataclasses import dataclass

from lughus import ToolRegistry

registry = ToolRegistry()


@dataclass
class AgentState:
    greeting: str = ""


@registry.tool(
    "greet",
    "Greet a person by name.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name to greet."},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
def greet(*, name: str, state: AgentState) -> str:
    state.greeting = f"Hello {name}!"
    return json.dumps({"greeting": state.greeting})
'''


def _workspace() -> str:
    return '''"""Request orchestration."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from lughus import CompletionEvent, ProgressEvent, ToolExecutionConfig, agent_loop

from .tools import AgentState, registry

SYSTEM_PROMPT = "You are a concise assistant. Use the greet tool when a name is provided."


class Workspace:
    def __init__(self, objective: str, llm: Any, tool_config: ToolExecutionConfig):
        self.objective = objective
        self.llm = llm
        self.tool_config = tool_config
        self.state = AgentState()

    async def run(self) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        yield ProgressEvent("Processing request")
        result = await agent_loop(
            self.llm,
            system=SYSTEM_PROMPT,
            context=self.objective,
            registry=registry,
            tool_names=["greet"],
            state=self.state,
            tool_config=self.tool_config,
        )
        yield CompletionEvent(text=result)
'''


def _gateway(class_prefix: str) -> str:
    return f'''"""A2A gateway."""
from __future__ import annotations

from collections.abc import AsyncIterator

from lughus import BaseGateway, CompletionEvent, ProgressEvent, ToolExecutionConfig

from .workspace import Workspace


class {class_prefix}Gateway(BaseGateway):
    async def handle(
        self,
        objective: str,
        files: list[tuple[bytes, str, str]],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        tool_config = ToolExecutionConfig(
            max_parallel_tools=self.settings.max_parallel_tools,
            max_global_tools=self.settings.max_global_tools,
            max_sync_thread_workers=self.settings.max_sync_thread_workers,
            tool_timeout=self.settings.tool_timeout,
            tool_queue_timeout=self.settings.tool_queue_timeout,
            max_tool_args_chars=self.settings.max_tool_args_chars,
            max_tool_output_chars=self.settings.max_tool_output_chars,
            max_message_history_chars=self.settings.max_message_history_chars,
            compact_tool_schemas=self.settings.compact_tool_schemas,
        )
        workspace = Workspace(objective, self.llm, tool_config)
        async for event in workspace.run():
            yield event
'''


def _task_store() -> str:
    return '''"""Production task store hook.

Replace this placeholder with a Redis, SQL, or other persistent TaskStore for
high-volume production deployments.
"""
from __future__ import annotations

from lughus import BoundedInMemoryTaskStore


class AgentTaskStore(BoundedInMemoryTaskStore):
    """Development-only store; replace it before production deployment."""
'''


def _main(
    *,
    package_name: str,
    class_prefix: str,
    display_name: str,
    description: str,
    skill_id: str,
    skill_name: str,
) -> str:
    return f'''"""Run the {display_name} lughus agent."""
from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from lughus import LLM, build_app, serve

from .config import Settings
from .gateway import {class_prefix}Gateway
from .task_store import AgentTaskStore

settings = Settings()

agent_card = AgentCard(
    name="{display_name}",
    version="0.1.0",
    url=settings.public_url or f"http://{{settings.host}}:{{settings.port}}",
    description="{description}",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="{skill_id}",
            name="{skill_name}",
            description="Greets a named person.",
            tags=["example"],
        )
    ],
    capabilities=AgentCapabilities(streaming=True),
)

llm = LLM.from_settings(settings)
gateway = {class_prefix}Gateway(llm=llm, settings=settings)
task_store = AgentTaskStore()

# ASGI entrypoint for uvicorn/gunicorn:
app = build_app(
    agent_card,
    gateway,
    task_store=task_store,
    enable_test_ui=settings.enable_test_ui,
)


def main() -> None:
    serve(
        agent_card,
        gateway,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        task_store=task_store,
        setup_otel=False,
        enable_test_ui=settings.enable_test_ui,
    )


if __name__ == "__main__":
    main()
'''


def _test_workspace(package_name: str) -> str:
    return f'''"""Offline tests for the generated agent."""
from __future__ import annotations

import pytest

from {package_name}.workspace import Workspace
from lughus import CompletionEvent, ProgressEvent, ToolExecutionConfig
from lughus.testing import MockLLM


@pytest.mark.asyncio
async def test_workspace_runs_with_mock_llm() -> None:
    llm = MockLLM([
        [{{"id": "call_1", "name": "greet", "arguments": {{"name": "Ada"}}}}],
        "Greeting complete.",
    ])
    workspace = Workspace(
        "Greet Ada",
        llm,
        ToolExecutionConfig(max_parallel_tools=2, tool_timeout=1.0),
    )

    events = [event async for event in workspace.run()]

    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[-1], CompletionEvent)
    assert events[-1].text == "Greeting complete."
'''


def _pytest_ini() -> str:
    return """[pytest]
asyncio_mode = auto
pythonpath = .
addopts = --import-mode=importlib
"""


def create_agent(
    *,
    target: Path,
    project_name: str,
    package_name: str,
    display_name: str,
    description: str,
    skill_id: str,
    skill_name: str,
) -> list[Path]:
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory is not empty: {target}")

    class_prefix = _class_prefix(package_name)
    files = {
        "pyproject.toml": _pyproject(project_name, package_name),
        "README.md": _readme(project_name, package_name, display_name),
        ".env.example": _env_example(),
        "pytest.ini": _pytest_ini(),
        f"{package_name}/__init__.py": f'"""Generated {display_name} agent."""\n',
        f"{package_name}/config.py": _config(),
        f"{package_name}/tools.py": _tools(),
        f"{package_name}/workspace.py": _workspace(),
        f"{package_name}/gateway.py": _gateway(class_prefix),
        f"{package_name}/task_store.py": _task_store(),
        f"{package_name}/__main__.py": _main(
            package_name=package_name,
            class_prefix=class_prefix,
            display_name=display_name,
            description=description,
            skill_id=skill_id,
            skill_name=skill_name,
        ),
        "tests/test_workspace.py": _test_workspace(package_name),
    }

    written: list[Path] = []
    for relative, content in files.items():
        path = target / relative
        _write_file(path, content)
        written.append(path)
    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lughus", description="lughus command line tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create a new lughus agent project")
    new_parser.add_argument("name", nargs="?", help="Project directory name, e.g. agent_test")
    new_parser.add_argument("--dir", dest="directory", help="Target directory. Defaults to NAME.")
    new_parser.add_argument("--display-name", help="AgentCard display name.")
    new_parser.add_argument("--description", help="AgentCard description.")
    new_parser.add_argument("--skill-id", default="greet", help="Initial AgentSkill id.")
    new_parser.add_argument("--skill-name", default="Greet", help="Initial AgentSkill name.")
    new_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for missing display metadata before creating files.",
    )
    return parser


def _prompt(current: str, label: str) -> str:
    value = input(f"{label} [{current}]: ").strip()
    return value or current


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "new":
        raw_name = args.name
        if not raw_name:
            raw_name = input("Project name [my_agent]: ").strip() or "my_agent"

        package_name = _package_name(raw_name)
        target = Path(args.directory or raw_name)
        display_name = args.display_name or _display_name(package_name)
        description = args.description or f"{display_name} agent."
        skill_id = args.skill_id
        skill_name = args.skill_name

        if args.interactive:
            display_name = _prompt(display_name, "Agent display name")
            description = _prompt(description, "Agent description")
            skill_id = _prompt(skill_id, "Initial skill id")
            skill_name = _prompt(skill_name, "Initial skill name")

        try:
            create_agent(
                target=target,
                project_name=raw_name,
                package_name=package_name,
                display_name=display_name,
                description=description,
                skill_id=skill_id,
                skill_name=skill_name,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))

        print(f"Created lughus agent in {target}")
        print("")
        print("Next steps:")
        print(f"  cd {target}")
        print('  python -m pip install -e ".[dev]"')
        print("  pytest -q")
        print(f"  python -m {package_name}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
