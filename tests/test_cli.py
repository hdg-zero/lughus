from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

from lughus.cli import _package_name, create_agent, main


def test_package_name_is_python_safe() -> None:
    assert _package_name("Agent Test") == "agent_test"
    assert _package_name("123-agent") == "agent_123_agent"


def test_package_name_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        _package_name("!!!")


def test_new_command_creates_agent_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "agent_test"

    exit_code = main(["new", "agent_test", "--dir", str(target)])

    assert exit_code == 0
    assert (target / "pyproject.toml").is_file()
    assert (target / "README.md").is_file()
    assert (target / ".env.example").is_file()
    assert (target / "agent_test" / "__main__.py").is_file()
    assert (target / "agent_test" / "workspace.py").is_file()
    assert (target / "tests" / "test_workspace.py").is_file()
    main_file = (target / "agent_test" / "__main__.py").read_text(encoding="utf-8")
    gateway_file = (target / "agent_test" / "gateway.py").read_text(encoding="utf-8")
    task_store_file = (target / "agent_test" / "task_store.py").read_text(encoding="utf-8")
    env_file = (target / ".env.example").read_text(encoding="utf-8")
    assert 'default_input_modes=["text/plain"]' in main_file
    assert 'default_output_modes=["text/plain"]' in main_file
    assert "settings.public_url" in main_file
    assert "LLM.from_settings(settings)" in main_file
    assert "max_sync_thread_workers=self.settings.max_sync_thread_workers" in gateway_file
    assert "tool_queue_timeout=self.settings.tool_queue_timeout" in gateway_file
    assert "max_message_history_chars=self.settings.max_message_history_chars" in gateway_file
    assert "compact_tool_schemas=self.settings.compact_tool_schemas" in gateway_file
    assert "BoundedInMemoryTaskStore" in task_store_file
    assert "from a2a.server.tasks import InMemoryTaskStore" not in task_store_file
    assert "PUBLIC_URL=" in env_file
    assert "LUGHUS_ENV=development" in env_file
    assert "API_BEARER_TOKEN=" in env_file
    assert "MAX_HTTP_BODY_BYTES=83886080" in env_file
    assert "MAX_ARTIFACT_BYTES=52428800" in env_file
    assert "MAX_TOTAL_ARTIFACT_BYTES=104857600" in env_file
    assert "MAX_CONCURRENT_REQUESTS=0" in env_file
    assert "MAX_QUEUE_BACKLOG=0" in env_file
    assert "TOOL_QUEUE_TIMEOUT=30" in env_file
    assert "COMPACT_TOOL_SCHEMAS=false" in env_file
    assert "Created lughus agent" in capsys.readouterr().out


def test_generated_python_files_compile(tmp_path: Path) -> None:
    target = tmp_path / "agent-test"
    main(["new", "agent-test", "--dir", str(target)])

    for path in (target / "agent_test").glob("*.py"):
        py_compile.compile(str(path), doraise=True)
    py_compile.compile(str(target / "tests" / "test_workspace.py"), doraise=True)


def test_create_agent_refuses_non_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "agent_test"
    target.mkdir()
    (target / "existing.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        create_agent(
            target=target,
            project_name="agent_test",
            package_name="agent_test",
            display_name="agent-test",
            description="Agent test.",
            skill_id="greet",
            skill_name="Greet",
        )
