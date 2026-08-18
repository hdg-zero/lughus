"""Tests for LLM generation parameters."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import litellm
import pytest

from lughus.llm import LLM


def _fake_response() -> litellm.ModelResponse:
    return litellm.ModelResponse(
        choices=[
            {
                "message": {"role": "assistant", "content": "ok"},
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        model="test-model",
    )


@pytest.mark.asyncio
async def test_params_reach_generate() -> None:
    """Custom params are forwarded to litellm.acompletion in generate()."""
    mock = AsyncMock(return_value=_fake_response())
    with patch("litellm.acompletion", mock):
        llm = LLM("test-model", params={"temperature": 0, "seed": 42}, max_retries=0)
        await llm.generate(messages=[{"role": "user", "content": "hi"}])

    _, kwargs = mock.call_args
    assert kwargs["temperature"] == 0
    assert kwargs["seed"] == 42


@pytest.mark.asyncio
async def test_params_reach_astream() -> None:
    """Custom params are forwarded to litellm.acompletion in astream()."""
    mock = AsyncMock(return_value=_fake_response())
    with patch("litellm.acompletion", mock):
        llm = LLM("test-model", params={"temperature": 0, "seed": 42}, max_retries=0)
        await llm.astream(messages=[{"role": "user", "content": "hi"}])

    _, kwargs = mock.call_args
    assert kwargs["temperature"] == 0
    assert kwargs["seed"] == 42


@pytest.mark.parametrize("key", ["messages", "tools", "stream", "stream_options", "model"])
def test_reserved_key_raises(key: str) -> None:
    """Reserved keys in params raise ValueError at construction time."""
    with pytest.raises(ValueError, match=key):
        LLM("test-model", params={key: "x"})


def test_mutation_after_construction_has_no_effect() -> None:
    """Mutating the original dict after construction does not affect the LLM."""
    d = {"temperature": 0}
    llm = LLM("test-model", params=d)
    d["temperature"] = 99
    assert llm.params["temperature"] == 0


def test_params_default_is_empty() -> None:
    """Default params is an empty dict."""
    assert LLM("test-model").params == {}
