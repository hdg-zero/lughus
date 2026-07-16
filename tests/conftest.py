"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest

from lughus import ToolRegistry
from lughus.config import BaseSettings


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh ToolRegistry for each test."""
    return ToolRegistry()


@pytest.fixture
def settings(monkeypatch) -> BaseSettings:
    """BaseSettings with AGENT_MODEL set — validates the monkeypatch fix (B3)."""
    monkeypatch.setenv("AGENT_MODEL", "test/mock-model")
    return BaseSettings()
