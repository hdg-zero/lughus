#!/usr/bin/env python3
"""Generate ``api_snapshot.json`` from the public API surface of *lughus*.

The snapshot records every name in ``lughus.__all__`` together with its
*kind* (class / dataclass / enum / function / constant) and, for plain
functions, the parameter list.  The result is written as sorted JSON to
the repository root so that ``tests/test_api_surface.py`` can detect
unintentional changes.

Usage:
    python scripts/update_api_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Ensure the repo root is on sys.path so ``import lughus`` works
# when the package is installed in editable mode or via pythonpath.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

SNAPSHOT_PATH = _REPO_ROOT / "api_snapshot.json"


def collect_api_surface() -> list[dict[str, object]]:
    """Return a sorted list of API-surface entries for every ``__all__`` name."""
    import enum
    import inspect

    import lughus

    entries: list[dict[str, object]] = []

    for name in sorted(lughus.__all__):
        entry: dict[str, object] = {"name": name}

        try:
            obj = getattr(lughus, name)
        except Exception:
            # Symbol requires an optional extra that is not installed.
            entry["kind"] = "unresolvable"
            entries.append(entry)
            continue

        # Determine kind.
        if isinstance(obj, type):
            if issubclass(obj, enum.Enum):
                entry["kind"] = "enum"
            elif hasattr(obj, "__dataclass_fields__"):
                entry["kind"] = "dataclass"
            else:
                entry["kind"] = "class"
        elif callable(obj):
            entry["kind"] = "function"
        else:
            entry["kind"] = "constant"

        # For plain functions, capture parameter names.
        if entry["kind"] == "function":
            try:
                sig = inspect.signature(obj)
                entry["parameters"] = [p.name for p in sig.parameters.values()]
            except (ValueError, TypeError):
                entry["parameters"] = []

        entries.append(entry)

    return entries


def main() -> int:
    entries = collect_api_surface()
    SNAPSHOT_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(entries)} entries to {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
