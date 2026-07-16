"""Tests for LLM retry on transient errors (J2-1)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import litellm
import pytest

from lughus.llm import LLM, retry_budget
from lughus.config import BaseSettings


def _make_text_response(text: str) -> MagicMock:
    """Build a fake non-streaming LLM response with text content."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = None
    return response


@pytest.mark.asyncio
async def test_llm_retry_on_rate_limit(monkeypatch) -> None:
    """LLM retries on RateLimitError and succeeds on the next try."""
    call_count = 0

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise litellm.RateLimitError("429 Rate Limit", "openai", "test/model")
        return _make_text_response("Success after retry")

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # Use max_retries=2, retry_base_delay=0.0 to avoid sleeping in tests
    llm = LLM("test/model", max_retries=2, retry_base_delay=0.0)
    result = await llm.generate(messages=[{"role": "user", "content": "hi"}])

    assert result.choices[0].message.content == "Success after retry"
    assert call_count == 3


@pytest.mark.asyncio
async def test_llm_retry_exceeded_raises(monkeypatch) -> None:
    """If transient error persists beyond max_retries, it is raised."""
    call_count = 0

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise litellm.ServiceUnavailableError("503 Overloaded", "openai", "test/model")

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=2, retry_base_delay=0.0)

    with pytest.raises(litellm.ServiceUnavailableError):
        await llm.generate(messages=[{"role": "user", "content": "hi"}])

    # 1 initial try + 2 retries = 3 attempts total
    assert call_count == 3


@pytest.mark.asyncio
async def test_llm_non_retryable_error_raises_immediately(monkeypatch) -> None:
    """BadRequestError should not trigger retries."""
    call_count = 0

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise litellm.BadRequestError("400 Bad Request", "test/model", "openai")

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=2, retry_base_delay=0.0)

    with pytest.raises(litellm.BadRequestError):
        await llm.generate(messages=[{"role": "user", "content": "hi"}])

    assert call_count == 1


@pytest.mark.asyncio
async def test_llm_retry_uses_retry_after(monkeypatch) -> None:
    """Retry-After headers override exponential jitter delay."""
    sleeps: list[float] = []
    call_count = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            exc = litellm.RateLimitError("429 Rate Limit", "openai", "test/model")
            exc.headers = {"Retry-After": "0.25"}
            raise exc
        return _make_text_response("ok")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=1, retry_base_delay=10.0)
    result = await llm.generate(messages=[{"role": "user", "content": "hi"}])

    assert result.choices[0].message.content == "ok"
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_llm_retry_budget_stops_retry(monkeypatch) -> None:
    """Retry budget prevents sleeping past the configured retry delay ceiling."""
    call_count = 0

    async def fake_sleep(delay: float) -> None:
        raise AssertionError("sleep should not be called when retry budget is exceeded")

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        exc = litellm.RateLimitError("429 Rate Limit", "openai", "test/model")
        exc.headers = {"Retry-After": "2.0"}
        raise exc

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=3, retry_base_delay=0.0, retry_max_elapsed=1.0)

    with pytest.raises(litellm.RateLimitError):
        await llm.generate(messages=[{"role": "user", "content": "hi"}])

    assert call_count == 1


@pytest.mark.asyncio
async def test_llm_retry_budget_is_shared_in_context(monkeypatch) -> None:
    """retry_budget() shares one retry sleep budget across multiple LLM calls."""
    sleeps: list[float] = []
    call_count = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count in (1, 3):
            exc = litellm.RateLimitError("429 Rate Limit", "openai", "test/model")
            exc.headers = {"Retry-After": "0.4"}
            raise exc
        return _make_text_response("ok")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=1, retry_base_delay=0.0)

    with retry_budget(0.5):
        await llm.generate(messages=[{"role": "user", "content": "one"}])
        with pytest.raises(litellm.RateLimitError):
            await llm.generate(messages=[{"role": "user", "content": "two"}])

    assert sleeps == [0.4]
    assert call_count == 3


@pytest.mark.asyncio
async def test_llm_retries_call_timeout(monkeypatch) -> None:
    """asyncio wait_for timeouts are treated as transient LLM errors."""
    call_count = 0

    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return _make_text_response("too late")

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", timeout=0.01, max_retries=1, retry_base_delay=0.0)

    with pytest.raises(TimeoutError):
        await llm.generate(messages=[{"role": "user", "content": "hi"}])

    assert call_count == 2


def test_llm_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL", "test/model")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "123")
    monkeypatch.setenv("LLM_TIMEOUT", "4.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("LLM_RETRY_BASE_DELAY", "0.25")
    monkeypatch.setenv("LLM_RETRY_MAX_ELAPSED", "2.0")

    llm = LLM.from_settings(BaseSettings())

    assert llm.model == "test/model"
    assert llm.max_output_tokens == 123
    assert llm.timeout == pytest.approx(4.5)
    assert llm.max_retries == 5
    assert llm.retry_base_delay == pytest.approx(0.25)
    assert llm.retry_max_elapsed == pytest.approx(2.0)
