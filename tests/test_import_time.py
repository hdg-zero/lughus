"""import-time budget for ``import lughus``.

A cold subprocess import must complete well under a generous CI threshold
(500 ms) to avoid penalising CLI start-up, serverless cold starts, and
fast-running test suites.  The production target is 150 ms on a
developer laptop; the test uses a wider bound for noisy CI runners.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# Generous threshold to accommodate slow CI runners.  The production
# target is 150 ms; 500 ms gives ~3x headroom for virtualised / cold
# environments.
_THRESHOLD_MS = 500


@pytest.mark.slow
def test_import_lughus_under_threshold() -> None:
    """Cold ``import lughus`` must complete within the time budget."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import time; t = time.perf_counter(); "
                "import lughus; "
                "print(int((time.perf_counter() - t) * 1000))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    elapsed_ms = int(result.stdout.strip())
    assert elapsed_ms < _THRESHOLD_MS, (
        f"import lughus took {elapsed_ms} ms, exceeding the {_THRESHOLD_MS} ms threshold"
    )
