"""CLI entry point: ``python -m benchmarks --all --out bench.json``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .scenarios import ALL_SCENARIOS


async def _run(names: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in names:
        fn = ALL_SCENARIOS[name]
        result = await fn()
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Run lughus framework benchmarks.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios.",
    )
    parser.add_argument(
        "--scenario",
        choices=list(ALL_SCENARIOS),
        action="append",
        default=[],
        help="Run a specific scenario (repeatable).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Write JSON results to this file (default: stdout).",
    )
    args = parser.parse_args()

    if args.all:
        names = list(ALL_SCENARIOS)
    elif args.scenario:
        names = args.scenario
    else:
        parser.error("Specify --all or at least one --scenario.")
        return

    results = asyncio.run(_run(names))

    output = json.dumps(results, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Results written to {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
