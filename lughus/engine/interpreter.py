"""Sandboxed Python code interpreter tool for agent loops.

Executes generated Python in an isolated subprocess (``python -I``) with a
dedicated temporary working directory, captures stdout/stderr, and reports
files produced during execution. The tool function follows the standard
``registry.tool`` signature (``state: dict`` keyword plus the schema params)
so it plugs into the normal ToolRuntime pipeline.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def register_code_interpreter(registry: Any, *, timeout_s: float = 30.0) -> str:
    """Register ``code_interpreter`` on *registry*; returns the tool name."""
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
            "Execute a short Python snippet in a sandboxed interpreter and return "
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
        requires_approval=False,
    )(run_impl)
    return name
