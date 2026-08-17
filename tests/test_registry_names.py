"""W1-12: the registry exposes its tool names publicly."""

from __future__ import annotations

from lughus import ToolRegistry


def build() -> ToolRegistry:
    reg = ToolRegistry()
    schema = {"type": "object", "properties": {}, "additionalProperties": False}

    @reg.tool("beta", "Second", schema)
    def beta(*, state) -> str:
        return "b"

    @reg.tool("alpha", "First", schema)
    def alpha(*, state) -> str:
        return "a"

    return reg


def test_names_are_returned_in_registration_order() -> None:
    assert build().names() == ("beta", "alpha")


def test_contains_and_len() -> None:
    reg = build()
    assert "alpha" in reg
    assert "missing" not in reg
    assert 123 not in reg  # non-str must not raise
    assert len(reg) == 2


def test_names_is_immutable() -> None:
    """A tuple, so a caller cannot mutate the registry's internals through it."""
    assert isinstance(build().names(), tuple)


def test_the_core_no_longer_reaches_into_private_state() -> None:
    """Regression guard: application.py used registry._tools.keys()."""
    import pathlib

    source = pathlib.Path(__import__("lughus").__file__).parent / "application.py"
    assert "registry._tools" not in source.read_text()
