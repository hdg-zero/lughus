"""both structures of InMemoryEventSink must be bounded."""

from __future__ import annotations

import pytest

from lughus.core.domain import RunEvent
from lughus.core.event_stream import InMemoryEventSink


def event(run_id: str, sequence: int) -> RunEvent:
    return RunEvent(type="run.started", run_id=run_id, sequence=sequence, data={})


async def test_sequence_tracker_is_bounded() -> None:
    """Fails on 0.10.1: _last_sequence grew by one entry per run, forever."""
    sink = InMemoryEventSink(max_events=100, max_tracked_runs=32)
    for i in range(1000):
        await sink.append(event(f"run-{i}", 0))
    assert len(sink._last_sequence) <= 32
    assert len(sink.snapshot()) <= 100


async def test_sequence_regression_still_detected_for_a_recent_run() -> None:
    sink = InMemoryEventSink(max_events=100, max_tracked_runs=32)
    await sink.append(event("run-a", 0))
    await sink.append(event("run-a", 1))
    with pytest.raises(ValueError, match="strictly increasing"):
        await sink.append(event("run-a", 1))


async def test_recently_seen_runs_are_kept_over_older_ones() -> None:
    sink = InMemoryEventSink(max_events=100, max_tracked_runs=4)
    for i in range(4):
        await sink.append(event(f"run-{i}", 0))
    # Touch run-0 so it becomes the most recently seen.
    await sink.append(event("run-0", 1))
    await sink.append(event("run-new", 0))

    assert "run-0" in sink._last_sequence, "recently active run must be retained"
    assert "run-1" not in sink._last_sequence, "least recently seen run is dropped"


async def test_snapshot_filtering_is_unchanged() -> None:
    sink = InMemoryEventSink(max_events=100)
    await sink.append(event("run-a", 0))
    await sink.append(event("run-b", 0))
    await sink.append(event("run-a", 1))
    assert len(sink.snapshot("run-a")) == 2
    assert len(sink.snapshot("run-b")) == 1
    assert len(sink.snapshot()) == 3


def test_bounds_must_be_positive() -> None:
    with pytest.raises(ValueError):
        InMemoryEventSink(max_events=0)
    with pytest.raises(ValueError):
        InMemoryEventSink(max_tracked_runs=0)
