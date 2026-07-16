"""Tests for ToolRegistry."""
from __future__ import annotations

import json
import logging

import pytest

from lughus import ToolRegistry, ToolValidationError


def test_register_sync_tool(registry: ToolRegistry) -> None:
    """A sync tool is registered and retrievable."""
    @registry.tool("my_tool", "A test tool.", {"type": "object", "properties": {}})
    def my_tool(*, state) -> str:
        return json.dumps({"ok": True})

    fn = registry.get_fn("my_tool")
    assert fn is not None
    assert fn(state=None) == '{"ok": true}'


def test_register_async_tool(registry: ToolRegistry) -> None:
    """An async tool is registered and retrievable."""
    @registry.tool("async_tool", "An async test tool.", {"type": "object", "properties": {}})
    async def async_tool(*, state) -> str:
        return json.dumps({"async": True})

    fn = registry.get_fn("async_tool")
    assert fn is not None


def test_invalid_tool_schema_raises(registry: ToolRegistry) -> None:
    """Invalid JSON Schema is rejected at registration time."""
    with pytest.raises(ToolValidationError, match="Invalid schema"):
        registry.tool("bad", "Bad schema.", {"type": "not-a-jsonschema-type"})


def test_duplicate_tool_name_raises(registry: ToolRegistry) -> None:
    @registry.tool("same", "First.", {"type": "object", "properties": {}})
    def first(*, state) -> str:
        return "first"

    with pytest.raises(ToolValidationError, match="already registered"):
        registry.tool("same", "Second.", {"type": "object", "properties": {}})


def test_tool_without_state_raises(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="state"):
        @registry.tool("bad_signature", "Missing state.", {"type": "object", "properties": {}})
        def bad_signature() -> str:
            return "bad"


def test_tool_with_positional_only_parameter_raises(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="positional-only"):
        @registry.tool(
            "bad_positional",
            "Uses positional-only args.",
            {"type": "object", "properties": {"value": {"type": "string"}}},
        )
        def bad_positional(value, /, *, state) -> str:
            return value


def test_schema_parameters_must_match_callable(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="not accepted"):
        @registry.tool(
            "schema_mismatch",
            "Schema has an unknown parameter.",
            {"type": "object", "properties": {"missing": {"type": "string"}}},
        )
        def schema_mismatch(*, state) -> str:
            return "bad"


def test_schema_parameters_can_use_kwargs(registry: ToolRegistry) -> None:
    @registry.tool(
        "kwargs_tool",
        "Accepts schema parameters through kwargs.",
        {"type": "object", "properties": {"value": {"type": "string"}}},
    )
    def kwargs_tool(*, state, **kwargs) -> str:
        return json.dumps(kwargs)

    fn = registry.get_fn("kwargs_tool")
    assert fn is not None
    assert json.loads(fn(state=None, value="ok")) == {"value": "ok"}


def test_get_fn_unknown_returns_none(registry: ToolRegistry) -> None:
    """get_fn() returns None for unknown tools (no exception)."""
    assert registry.get_fn("does_not_exist") is None


def test_declarations_returns_openai_format(registry: ToolRegistry) -> None:
    """declarations() returns correctly shaped OpenAI-format dicts."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    @registry.tool("my_tool", "Description.", schema)
    def my_tool(*, x: str, state) -> str:
        return x

    decls = registry.declarations(["my_tool"])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["type"] == "function"
    assert decl["function"]["name"] == "my_tool"
    assert decl["function"]["description"] == "Description."
    assert decl["function"]["parameters"] == schema


def test_declarations_unknown_name_skipped_with_warning(
    registry: ToolRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    """declarations() skips unknown names and logs a warning (M5 fix)."""
    with caplog.at_level(logging.WARNING, logger="lughus.tools"):
        result = registry.declarations(["nonexistent"])

    assert result == []
    assert "nonexistent" in caplog.text
    assert "not found" in caplog.text


def test_declarations_unknown_name_can_be_strict(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="not registered"):
        registry.declarations(["nonexistent"], strict=True)


def test_declarations_empty_names(registry: ToolRegistry) -> None:
    """declarations([]) returns an empty list."""
    assert registry.declarations([]) == []


def test_declarations_order_preserved(registry: ToolRegistry) -> None:
    """declarations() preserves the order of requested tool names."""
    for name in ("z_tool", "a_tool", "m_tool"):
        @registry.tool(name, f"Tool {name}.", {"type": "object", "properties": {}})
        def _tool(*, state) -> str:
            return name

    decls = registry.declarations(["m_tool", "z_tool", "a_tool"])
    assert [d["function"]["name"] for d in decls] == ["m_tool", "z_tool", "a_tool"]


def test_registry_isolation() -> None:
    """Two ToolRegistry instances do not share tools."""
    r1, r2 = ToolRegistry(), ToolRegistry()

    @r1.tool("shared_name", "In r1.", {"type": "object", "properties": {}})
    def tool_r1(*, state) -> str:
        return "r1"

    assert r1.get_fn("shared_name") is not None
    assert r2.get_fn("shared_name") is None
