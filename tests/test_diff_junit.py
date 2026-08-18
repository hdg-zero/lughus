"""Tests for scripts/diff_junit.py -- differential JUnit comparison."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# Import the module under test directly; pytest.ini sets pythonpath = .
from scripts.diff_junit import main

PASSING_REPORT = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuite name="pytest" tests="3" failures="0" errors="0" skipped="0">
      <testcase classname="tests.test_a" name="test_one" time="0.01"/>
      <testcase classname="tests.test_a" name="test_two" time="0.02"/>
      <testcase classname="tests.test_b" name="test_three" time="0.01"/>
    </testsuite>
""")

ONE_FAILURE_REPORT = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuite name="pytest" tests="3" failures="1" errors="0" skipped="0">
      <testcase classname="tests.test_a" name="test_one" time="0.01"/>
      <testcase classname="tests.test_a" name="test_two" time="0.05">
        <failure message="assert False">AssertionError: assert False</failure>
      </testcase>
      <testcase classname="tests.test_b" name="test_three" time="0.01"/>
    </testsuite>
""")

DIFFERENT_FAILURE_REPORT = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuite name="pytest" tests="3" failures="1" errors="0" skipped="0">
      <testcase classname="tests.test_a" name="test_one" time="0.01">
        <failure message="assert 1 == 2">AssertionError</failure>
      </testcase>
      <testcase classname="tests.test_a" name="test_two" time="0.02"/>
      <testcase classname="tests.test_b" name="test_three" time="0.01"/>
    </testsuite>
""")


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_no_new_failures_both_passing(tmp_path: Path) -> None:
    """When both base and head have zero failures, exit 0."""
    base = _write(tmp_path, "base.xml", PASSING_REPORT)
    head = _write(tmp_path, "head.xml", PASSING_REPORT)
    assert main([str(base), str(head)]) == 0


def test_no_new_failures_same_failure(tmp_path: Path) -> None:
    """When head has the same failure as base, exit 0 (not a *new* failure)."""
    base = _write(tmp_path, "base.xml", ONE_FAILURE_REPORT)
    head = _write(tmp_path, "head.xml", ONE_FAILURE_REPORT)
    assert main([str(base), str(head)]) == 0


def test_one_new_failure(tmp_path: Path) -> None:
    """When head introduces a failure not present in base, exit 1."""
    base = _write(tmp_path, "base.xml", PASSING_REPORT)
    head = _write(tmp_path, "head.xml", ONE_FAILURE_REPORT)
    assert main([str(base), str(head)]) == 1


def test_disappeared_failure_is_not_new(tmp_path: Path) -> None:
    """When a base failure is fixed in head, exit 0 (not a new failure)."""
    base = _write(tmp_path, "base.xml", ONE_FAILURE_REPORT)
    head = _write(tmp_path, "head.xml", PASSING_REPORT)
    assert main([str(base), str(head)]) == 0


def test_swapped_failure_detects_new(tmp_path: Path) -> None:
    """Head fixes one failure but introduces a different one -- exit 1."""
    base = _write(tmp_path, "base.xml", ONE_FAILURE_REPORT)
    head = _write(tmp_path, "head.xml", DIFFERENT_FAILURE_REPORT)
    assert main([str(base), str(head)]) == 1


@pytest.mark.parametrize("args", [[], ["only-one.xml"]])
def test_usage_error(args: list[str]) -> None:
    """Wrong number of arguments returns exit code 2."""
    assert main(args) == 2


def test_missing_file(tmp_path: Path) -> None:
    """Non-existent file returns exit code 2."""
    existing = _write(tmp_path, "base.xml", PASSING_REPORT)
    assert main([str(existing), str(tmp_path / "nope.xml")]) == 2
