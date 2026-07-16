"""Tests for LoopResult — the str subclass with usage metadata."""

from __future__ import annotations

import copy
import json
import pickle

import pytest

from lughus.loop import LoopResult


def _result(text: str = "hello") -> LoopResult:
    return LoopResult(
        text,
        iterations=3,
        elapsed=1.23,
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=10,
    )


def test_str_behavior() -> None:
    """LoopResult behaves as a plain str."""
    r = _result("hello world")
    assert r == "hello world"
    assert len(r) == 11
    assert r.upper() == "HELLO WORLD"
    assert r + " !" == "hello world !"


def test_str_cast_drops_metadata() -> None:
    """str(result) returns a plain str without metadata (expected Python behavior)."""
    r = _result("hello")
    plain = str(r)
    assert type(plain) is str
    assert plain == "hello"
    assert not hasattr(plain, "iterations")


def test_metadata_attributes() -> None:
    """All metadata attributes are correctly stored."""
    r = _result()
    assert r.iterations == 3
    assert r.elapsed == pytest.approx(1.23)
    assert r.prompt_tokens == 100
    assert r.completion_tokens == 50
    assert r.cached_tokens == 10


def test_total_tokens() -> None:
    """total_tokens is the sum of prompt + completion."""
    r = _result()
    assert r.total_tokens == 150


def test_json_loads_passthrough() -> None:
    """LoopResult with JSON content works with json.loads() directly."""
    r = LoopResult(
        '{"key": "value"}',
        iterations=1,
        elapsed=0.1,
        prompt_tokens=5,
        completion_tokens=5,
        cached_tokens=0,
    )
    assert json.loads(r) == {"key": "value"}


def test_copy() -> None:
    """copy.copy() preserves all metadata."""
    r = _result("test")
    r2 = copy.copy(r)
    assert r2 == "test"
    assert r2.iterations == 3
    assert r2.elapsed == pytest.approx(1.23)
    assert r2.prompt_tokens == 100
    assert r2.completion_tokens == 50
    assert r2.cached_tokens == 10


def test_deepcopy() -> None:
    """copy.deepcopy() preserves all metadata."""
    r = _result("deep")
    r2 = copy.deepcopy(r)
    assert r2 == "deep"
    assert r2.total_tokens == 150


def test_pickle_round_trip() -> None:
    """pickle round-trip preserves text and all metadata."""
    r = _result("pickled")
    data = pickle.dumps(r)
    r2 = pickle.loads(data)
    assert r2 == "pickled"
    assert r2.iterations == 3
    assert r2.elapsed == pytest.approx(1.23)
    assert r2.prompt_tokens == 100
    assert r2.completion_tokens == 50
    assert r2.cached_tokens == 10
    assert r2.total_tokens == 150


def test_isinstance_str() -> None:
    """LoopResult is an instance of str."""
    r = _result()
    assert isinstance(r, str)
