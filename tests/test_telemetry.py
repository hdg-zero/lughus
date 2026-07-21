"""Tests for telemetry initialization."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import lughus.telemetry
from lughus.telemetry import setup_telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_initialized():
    """Ensure _INITIALIZED is False before and after each test."""
    lughus.telemetry._INITIALIZED = False
    yield
    lughus.telemetry._INITIALIZED = False


def test_telemetry_retryable_after_failure(monkeypatch) -> None:
    with patch("lughus.telemetry.Resource.create", side_effect=RuntimeError("simulated error")):
        with pytest.raises(RuntimeError, match="simulated error"):
            setup_telemetry("test")

    assert lughus.telemetry._INITIALIZED is False

    with patch("lughus.telemetry.Resource.create"):
        setup_telemetry("test")

    assert lughus.telemetry._INITIALIZED is True


def test_telemetry_idempotent_after_success(monkeypatch) -> None:
    monkeypatch.setenv("LUGHUS_TELEMETRY_CONSOLE", "true")

    with (
        patch("lughus.telemetry.Resource.create") as mock_resource,
        patch("lughus.telemetry.TracerProvider") as mock_tracer_provider,
        patch("lughus.telemetry.MeterProvider"),
        patch("lughus.telemetry.trace.set_tracer_provider"),
        patch("lughus.telemetry.metrics.set_meter_provider"),
    ):
        setup_telemetry("test")
        assert lughus.telemetry._INITIALIZED is True

        setup_telemetry("test")

        mock_resource.assert_called_once()
        mock_tracer_provider.assert_called_once()


def test_telemetry_configures_logging_when_no_handlers(monkeypatch) -> None:
    """setup_telemetry configures logging when root logger has no handlers."""
    import logging

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    try:
        with patch("lughus.telemetry.Resource.create"):
            setup_telemetry("test", configure_logging=True)
        assert len(root.handlers) > 0
    finally:
        root.handlers[:] = original_handlers


def test_telemetry_skips_logging_when_disabled(monkeypatch) -> None:
    """setup_telemetry skips logging setup when configure_logging=False."""
    import logging

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        with patch("lughus.telemetry.Resource.create"):
            setup_telemetry("test", configure_logging=False)
        assert len(root.handlers) == 0
    finally:
        root.handlers[:] = original_handlers
