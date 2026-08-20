"""Verify that Python code blocks in README.md parse without syntax errors.

Extracts fenced Python code blocks from README.md and compiles each one.
Self-contained examples (those that import only from lughus/lughus.testing
and use asyncio.run) are executed to verify they actually work.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import pytest

_README = Path(__file__).resolve().parent.parent / "README.md"


def _extract_python_blocks(md_text: str) -> list[tuple[int, str]]:
    """Return (line_number, code) pairs for each ```python block."""
    blocks: list[tuple[int, str]] = []
    pattern = re.compile(r"^```python\s*$", re.MULTILINE)
    for match in pattern.finditer(md_text):
        start = md_text.count("\n", 0, match.start()) + 1
        rest = md_text[match.end() :]
        end_fence = rest.find("\n```")
        if end_fence == -1:
            continue
        code = rest[1:end_fence]  # skip the newline after ```python
        blocks.append((start, textwrap.dedent(code)))
    return blocks


_BLOCKS = _extract_python_blocks(_README.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "line,code",
    _BLOCKS,
    ids=[f"line_{line}" for line, _ in _BLOCKS],
)
def test_code_block_compiles(line: int, code: str) -> None:
    """Each Python code block must be valid syntax."""
    try:
        ast.parse(code, filename=f"README.md:L{line}")
    except SyntaxError as exc:
        pytest.fail(f"Syntax error in README.md code block at line {line}: {exc}")


def _is_self_contained(code: str) -> bool:
    """Check if a code block is runnable (has asyncio.run and imports from lughus)."""
    return "asyncio.run(" in code and "from lughus" in code


_RUNNABLE = [(line, code) for line, code in _BLOCKS if _is_self_contained(code)]


@pytest.mark.parametrize(
    "line,code",
    _RUNNABLE,
    ids=[f"line_{line}" for line, _ in _RUNNABLE],
)
def test_runnable_example(line: int, code: str) -> None:
    """Self-contained examples must execute without errors."""
    try:
        exec(compile(code, f"README.md:L{line}", "exec"), {"__name__": "__main__"})
    except Exception as exc:
        pytest.fail(f"README.md example at line {line} failed: {exc}")
