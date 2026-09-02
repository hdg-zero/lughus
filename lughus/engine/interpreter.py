"""Python code interpreter tool for agent loops.

Executes generated Python in an isolated subprocess (``python -I``) with a
dedicated temporary working directory, captures stdout/stderr, and reports
files produced during execution.

Security model & limitations:
-----------------------------
``python -I`` (Isolated Mode) ignores environment variables (``PYTHONPATH``,
``PYTHONHOME``), user site-packages, and the current directory for module lookup.
However, it does NOT provide an OS-level sandbox (no network restriction, no
filesystem chroot or seccomp filter). Because code execution poses significant
security risks, this tool is marked as ``ToolRisk.HIGH`` with
``requires_approval=True`` by default.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tools import ToolEffect, ToolRisk

__all__ = [
    "MAX_OUTPUT_CHARS",
    "InterpreterResult",
    "InterpreterTimeoutError",
    "register_code_interpreter",
]

MAX_OUTPUT_CHARS = 20_000


class InterpreterTimeoutError(TimeoutError):
    """Raised when interpreted code exceeds the allowed wall-clock time."""


@dataclass(frozen=True)
class InterpreterResult:
    """Outcome of one interpreted snippet."""

    exit_code: int
    stdout: str
    stderr: str
    files: tuple[str, ...]


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} characters]"


def run_python(code: str, timeout_s: float = 30.0) -> InterpreterResult:
    """Run *code* in a fresh isolated interpreter and capture its output."""
    with tempfile.TemporaryDirectory(prefix="lughus_interp_") as tmp:
        workdir = Path(tmp)
        script = workdir / "snippet.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=workdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise InterpreterTimeoutError(f"code_interpreter exceeded {timeout_s}s") from exc
        produced = sorted(
            p.name for p in workdir.iterdir() if p.name != "snippet.py" and p.is_file()
        )
        return InterpreterResult(
            exit_code=proc.returncode,
            stdout=_truncate(proc.stdout),
            stderr=_truncate(proc.stderr),
            files=tuple(produced),
        )


def register_code_interpreter(
    registry: Any,
    *,
    timeout_s: float = 30.0,
    requires_approval: bool = True,
) -> str:
    """Register ``code_interpreter`` on *registry*; returns the tool name.

    Parameters
    ----------
    registry:
        ToolRegistry instance to attach the tool to.
    timeout_s:
        Wall-clock timeout in seconds for script execution (default 30.0).
    requires_approval:
        Whether the tool invocation requires human approval (default True).
        Since Python execution is not fully sandboxed by the OS, human-in-the-loop
        approval is strongly recommended.
    """
    name = "code_interpreter"

    if name in registry:
        return name

    async def run_impl(*, state: dict, code: str) -> dict:
        del state
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, run_python, code, timeout_s)
        except InterpreterTimeoutError as exc:
            return {"exit_code": -1, "error": str(exc), "stdout": "", "stderr": "", "files": []}
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "files": list(result.files),
        }

    registry.tool(
        name,
        (
            "Execute a short Python snippet in an isolated subprocess (python -I) and return "
            "stdout, stderr, exit code and any files it wrote. Use it for "
            "computations, quick simulations or format conversions. The snippet "
            "must print its result to stdout."
        ),
        {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Complete Python source to execute. Print results with print().",
                }
            },
            "required": ["code"],
        },
        requires_approval=requires_approval,
        risk=ToolRisk.HIGH,
        effects=frozenset({ToolEffect.EXTERNAL, ToolEffect.WRITE}),
    )(run_impl)
    return name
