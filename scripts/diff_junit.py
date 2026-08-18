#!/usr/bin/env python3
"""Compare two JUnit XML reports and fail if new test failures appear.

Usage:
    python scripts/diff_junit.py reports/base.xml reports/head.xml

Exit codes:
    0 - No new failures detected.
    1 - New failures detected (present in head but not in base).
    2 - Usage / file-not-found error.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _test_key(tc: ET.Element) -> str:
    """Return a stable identifier for a <testcase> element."""
    classname = tc.get("classname", "")
    name = tc.get("name", "")
    return f"{classname}::{name}"


def _failed_keys(tree: ET.ElementTree) -> set[str]:
    """Extract the set of test-case keys that contain a <failure> or <error>."""
    failed: set[str] = set()
    for tc in tree.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            failed.add(_test_key(tc))
    return failed


def _summary(tree: ET.ElementTree) -> dict[str, int]:
    """Return aggregate counts from the root <testsuite(s)> element."""
    root = tree.getroot()
    # Handle both <testsuites> wrapper and single <testsuite>
    suites = list(root.iter("testsuite")) if root.tag == "testsuites" else [root]

    totals: dict[str, int] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for key in totals:
            totals[key] += int(s.get(key, "0"))
    return totals


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(f"Usage: {sys.argv[0]} <base.xml> <head.xml>", file=sys.stderr)
        return 2

    base_path, head_path = Path(args[0]), Path(args[1])
    for p in (base_path, head_path):
        if not p.exists():
            print(f"Error: file not found: {p}", file=sys.stderr)
            return 2

    base_tree = ET.parse(base_path)
    head_tree = ET.parse(head_path)

    base_failures = _failed_keys(base_tree)
    head_failures = _failed_keys(head_tree)
    new_failures = sorted(head_failures - base_failures)

    head_stats = _summary(head_tree)
    print(
        f"Head report: {head_stats['tests']} tests, "
        f"{head_stats['failures']} failures, "
        f"{head_stats['errors']} errors, "
        f"{head_stats['skipped']} skipped"
    )

    if new_failures:
        print(f"\n{len(new_failures)} NEW failure(s) not present in base:")
        for key in new_failures:
            print(f"  - {key}")
        return 1

    disappeared = sorted(base_failures - head_failures)
    if disappeared:
        print(f"\n{len(disappeared)} failure(s) fixed (present in base, absent in head):")
        for key in disappeared:
            print(f"  + {key}")

    print("\nNo new failures detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
