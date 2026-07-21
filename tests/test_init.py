"""Tests for lughus.__init__ lazy imports."""

from __future__ import annotations


def test_lazy_import_llm() -> None:
    """LLM is available via lazy __getattr__."""
    import lughus

    assert lughus.LLM is not None
    assert lughus.LLM.__name__ == "LLM"


def test_lazy_import_generate_llm() -> None:
    """GenerateLLM is available via lazy __getattr__."""
    import lughus

    assert lughus.GenerateLLM is not None


def test_lazy_import_streaming_llm() -> None:
    """StreamingLLM is available via lazy __getattr__."""
    import lughus

    assert lughus.StreamingLLM is not None


def test_lazy_import_unknown_raises() -> None:
    """Unknown attribute raises AttributeError."""
    import lughus
    import pytest

    with pytest.raises(AttributeError, match="no attribute"):
        _ = lughus.does_not_exist
