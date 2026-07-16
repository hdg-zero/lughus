"""Tests for agent timeout in BaseGateway.execute (J2-2)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, ANY

import pytest

from lughus.config import BaseSettings
from lughus.gateway import BaseGateway
from lughus.llm import LLM


class SlowGateway(BaseGateway):
    """Gateway that takes time to produce events."""
    async def handle(self, objective, files):
        from lughus.events import ProgressEvent
        yield ProgressEvent("started")
        await asyncio.sleep(0.5)
        yield ProgressEvent("finished")


class NoCompletionGateway(BaseGateway):
    """Gateway that returns progress but never completes."""
    async def handle(self, objective, files):
        from lughus.events import ProgressEvent
        yield ProgressEvent("started")


class CancellableGateway(BaseGateway):
    """Gateway that keeps running until cancelled."""

    def __init__(self, llm, settings):
        super().__init__(llm, settings)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def handle(self, objective, files):
        from lughus.events import ProgressEvent

        yield ProgressEvent("started")
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.mark.asyncio
async def test_gateway_execute_timeout(monkeypatch) -> None:
    """BaseGateway.execute fails with a timeout if handle takes too long."""
    # Configure tiny agent timeout
    monkeypatch.setenv("AGENT_MODEL", "test/model")
    monkeypatch.setenv("AGENT_TIMEOUT", "0.1")

    settings = BaseSettings()
    llm = MagicMock(spec=LLM)
    llm.model = "test/model"

    gateway = SlowGateway(llm=llm, settings=settings)

    # Mock context
    context = MagicMock()
    context.task_id = "task-123"
    context.context_id = "ctx-456"
    # _extract returns empty objective and files
    monkeypatch.setattr(gateway, "_extract", lambda ctx: ("", []))

    # Mock TaskUpdater and its methods
    mock_updater = MagicMock()
    mock_updater.start_work = AsyncMock()
    mock_updater.failed = AsyncMock()
    mock_updater.update_status = AsyncMock()
    mock_updater.complete = AsyncMock()
    mock_updater.new_agent_message = MagicMock(return_value="mock-message")

    monkeypatch.setattr("lughus.gateway.TaskUpdater", lambda *args, **kwargs: mock_updater)

    event_queue = MagicMock()

    await gateway.execute(context, event_queue)

    # Check if failed was called with a timeout message
    mock_updater.failed.assert_called_once()
    called_args, called_kwargs = mock_updater.failed.call_args
    # message parameter was passed
    assert called_kwargs.get("message") == "mock-message"
    mock_updater.new_agent_message.assert_any_call(parts=ANY)

    # Check that parts contain the timeout text
    timeout_call = [
        call for call in mock_updater.new_agent_message.call_args_list
        if any("timed out" in getattr(p.root, "text", "") for p in call.kwargs.get("parts", []))
    ]
    assert len(timeout_call) > 0


@pytest.mark.asyncio
async def test_gateway_execute_fails_without_completion(monkeypatch) -> None:
    """BaseGateway.execute must produce a terminal failure if handle ends early."""
    monkeypatch.setenv("AGENT_MODEL", "test/model")

    settings = BaseSettings()
    llm = MagicMock(spec=LLM)
    llm.model = "test/model"
    gateway = NoCompletionGateway(llm=llm, settings=settings)

    context = MagicMock()
    context.task_id = "task-123"
    context.context_id = "ctx-456"
    monkeypatch.setattr(gateway, "_extract", lambda ctx: ("", []))

    mock_updater = MagicMock()
    mock_updater.start_work = AsyncMock()
    mock_updater.failed = AsyncMock()
    mock_updater.update_status = AsyncMock()
    mock_updater.complete = AsyncMock()
    mock_updater.new_agent_message = MagicMock(return_value="mock-message")

    monkeypatch.setattr("lughus.gateway.TaskUpdater", lambda *args, **kwargs: mock_updater)

    await gateway.execute(context, MagicMock())

    mock_updater.update_status.assert_called_once()
    mock_updater.complete.assert_not_called()
    mock_updater.failed.assert_called_once()
    failure_call = [
        call for call in mock_updater.new_agent_message.call_args_list
        if any("without CompletionEvent" in getattr(p.root, "text", "") for p in call.kwargs.get("parts", []))
    ]
    assert len(failure_call) == 1


@pytest.mark.asyncio
async def test_gateway_cancel_stops_running_execute(monkeypatch) -> None:
    """BaseGateway.cancel cancels the in-process execute coroutine for the task."""
    monkeypatch.setenv("AGENT_MODEL", "test/model")

    settings = BaseSettings()
    llm = MagicMock(spec=LLM)
    llm.model = "test/model"
    gateway = CancellableGateway(llm=llm, settings=settings)

    context = MagicMock()
    context.task_id = "task-cancel"
    context.context_id = "ctx-cancel"
    monkeypatch.setattr(gateway, "_extract_async", AsyncMock(return_value=("", [])))

    mock_updater = MagicMock()
    mock_updater.start_work = AsyncMock()
    mock_updater.failed = AsyncMock()
    mock_updater.update_status = AsyncMock()
    mock_updater.complete = AsyncMock()
    mock_updater.cancel = AsyncMock()
    mock_updater.new_agent_message = MagicMock(return_value="mock-message")

    monkeypatch.setattr("lughus.gateway.TaskUpdater", lambda *args, **kwargs: mock_updater)

    execute_task = asyncio.create_task(gateway.execute(context, MagicMock()))
    await asyncio.wait_for(gateway.started.wait(), timeout=1)

    await gateway.cancel(context, MagicMock())
    await asyncio.wait_for(gateway.cancelled.wait(), timeout=1)
    await asyncio.wait_for(execute_task, timeout=1)

    mock_updater.cancel.assert_called_once()
    assert "task-cancel" not in gateway._running_tasks
