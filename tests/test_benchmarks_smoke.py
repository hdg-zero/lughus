"""Smoke tests: each benchmark scenario runs and produces all expected metric keys."""

from __future__ import annotations

import pytest

from benchmarks.scenarios import ALL_SCENARIOS, EXPECTED_METRIC_KEYS


@pytest.mark.parametrize("name", list(ALL_SCENARIOS))
async def test_scenario_produces_expected_keys(name: str) -> None:
    fn = ALL_SCENARIOS[name]
    result = await fn()

    assert isinstance(result, dict)
    actual_keys = set(result.keys())
    assert actual_keys == EXPECTED_METRIC_KEYS, (
        f"Scenario {name!r}: expected keys {sorted(EXPECTED_METRIC_KEYS)}, "
        f"got {sorted(actual_keys)}"
    )
    assert result["scenario"] == name


@pytest.mark.parametrize("name", list(ALL_SCENARIOS))
async def test_scenario_metrics_are_positive(name: str) -> None:
    fn = ALL_SCENARIOS[name]
    result = await fn()

    assert result["tokens_in"] > 0
    assert result["tokens_out"] > 0
    assert result["provider_calls"] > 0
    assert result["wall_time_s"] >= 0
    assert result["cpu_time_s"] >= 0
    assert result["prefix_size_bytes"] > 0
    # prefix must be 100% reused across all turns.
    assert result["prefix_reuse_pct"] == 100.0
