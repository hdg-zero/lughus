"""Tests for the sandboxed code_interpreter tool."""

from __future__ import annotations

import asyncio

import pytest

from lughus.engine.interpreter import (
    MAX_OUTPUT_CHARS,
    InterpreterTimeoutError,
    register_code_interpreter,
    run_python,
)
from lughus.engine.tools import ToolRegistry


class TestRunPython:
    def test_captures_stdout(self) -> None:
        result = run_python("print(2 + 3)")
        assert result.exit_code == 0
        assert result.stdout.strip() == "5"

    def test_captures_stderr_and_exit_code(self) -> None:
        result = run_python("import sys; sys.stderr.write('boom'); raise SystemExit(3)")
        assert result.exit_code == 3
        assert "boom" in result.stderr

    def test_lists_produced_files(self) -> None:
        code = "open('out.txt','w').write('hello')"
        result = run_python(code)
        assert result.exit_code == 0
        assert "out.txt" in result.files

    def test_timeout_raises(self) -> None:
        with pytest.raises(InterpreterTimeoutError):
            run_python("while True: pass", timeout_s=1.0)

    def test_output_truncated(self) -> None:
        result = run_python(f"print('x' * {MAX_OUTPUT_CHARS * 3})")
        assert len(result.stdout) < MAX_OUTPUT_CHARS * 3
        assert "truncated" in result.stdout


class TestRegisterCodeInterpreter:
    def test_registers_tool_on_registry(self) -> None:
        registry = ToolRegistry()
        name = register_code_interpreter(registry)
        assert name in registry

    def test_idempotent_registration(self) -> None:
        registry = ToolRegistry()
        assert register_code_interpreter(registry) == register_code_interpreter(registry)

    def test_tool_executes_code(self) -> None:
        registry = ToolRegistry()
        register_code_interpreter(registry)
        tool_def = registry._tools["code_interpreter"]
        outcome = asyncio.run(tool_def.fn(state={}, code="print('ok')"))
        assert outcome["exit_code"] == 0
        assert outcome["stdout"].strip() == "ok"

    def test_tool_reports_timeout_gracefully(self) -> None:
        registry = ToolRegistry()
        register_code_interpreter(registry, timeout_s=1.0)
        tool_def = registry._tools["code_interpreter"]
        outcome = asyncio.run(tool_def.fn(state={}, code="while True: pass"))
        assert outcome["exit_code"] == -1
        assert "exceeded" in outcome["error"]

    def test_security_defaults(self) -> None:
        from lughus.engine.tools import ToolEffect, ToolRisk

        registry = ToolRegistry()
        register_code_interpreter(registry)
        tool_def = registry._tools["code_interpreter"]
        assert tool_def.requires_approval is True
        assert tool_def.risk == ToolRisk.HIGH
        assert ToolEffect.EXTERNAL in tool_def.effects
        assert ToolEffect.WRITE in tool_def.effects

    def test_custom_approval_flag(self) -> None:
        registry = ToolRegistry()
        register_code_interpreter(registry, requires_approval=False)
        tool_def = registry._tools["code_interpreter"]
        assert tool_def.requires_approval is False
