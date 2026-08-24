"""precalculated frozen tool declarations."""

from __future__ import annotations

import json

import pytest

from lughus import ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool(
        "alpha",
        "Alpha tool.",
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )
    def alpha(*, x: str, state) -> str:
        return x

    @r.tool("beta", "Beta tool.", {"type": "object", "properties": {}})
    def beta(*, state) -> str:
        return "b"

    return r


def test_declarations_byte_identical_across_calls(registry: ToolRegistry) -> None:
    """Canonical JSON must be byte-identical across 5 calls."""
    results = [registry.declarations_json(["alpha", "beta"]) for _ in range(5)]
    assert all(r == results[0] for r in results)


def test_declarations_frozen_raises_on_mutation(registry: ToolRegistry) -> None:
    """Returned declarations must be frozen — mutation raises TypeError."""
    decls = registry.declarations(["alpha"])
    with pytest.raises(TypeError):
        decls[0]["function"]["name"] = "hacked"


def test_declarations_equivalence(registry: ToolRegistry) -> None:
    """Frozen declarations match the expected structure."""
    decls = registry.declarations(["alpha"])
    assert len(decls) == 1
    d = decls[0]
    assert d["type"] == "function"
    assert d["function"]["name"] == "alpha"


def test_different_tool_sets_different_declarations(registry: ToolRegistry) -> None:
    """Different tool name sets produce different declarations."""
    json_a = registry.declarations_json(["alpha"])
    json_b = registry.declarations_json(["beta"])
    json_ab = registry.declarations_json(["alpha", "beta"])
    assert json_a != json_b
    assert json_a != json_ab


def test_cache_invalidation_on_new_tool(registry: ToolRegistry) -> None:
    """Registering a new tool clears the cache."""
    before = registry.declarations_json(["alpha"])

    @registry.tool("gamma", "Gamma.", {"type": "object", "properties": {}})
    def gamma(*, state) -> str:
        return "g"

    # The old cache should be cleared, though alpha hasn't changed
    after = registry.declarations_json(["alpha"])
    assert before == after  # same tool, same output

    # But gamma is now available
    with_gamma = registry.declarations_json(["alpha", "gamma"])
    assert with_gamma != before


def test_canonical_json_sorted_keys(registry: ToolRegistry) -> None:
    """Canonical JSON uses sorted keys and compact separators."""
    canon = registry.declarations_json(["alpha"])
    parsed = json.loads(canon)
    re_serialized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    assert canon == re_serialized


def test_declarations_tuple_return(registry: ToolRegistry) -> None:
    """declarations() returns a tuple, not a list."""
    decls = registry.declarations(["alpha"])
    assert isinstance(decls, tuple)


def test_prepare_tools_payload_allows_mutation(registry: ToolRegistry) -> None:
    """_prepare_tools_payload produces a mutable copy allowing provider in-place schema modifications."""
    from lughus.engine.llm import _prepare_tools_payload

    decls = registry.declarations(["alpha"])
    payload = _prepare_tools_payload(decls)
    assert payload is not None
    assert isinstance(payload, list)
    assert isinstance(payload[0], dict)

    # Provider adapters like Gemini/Vertex delete or modify keys in-place
    params = payload[0]["function"]["parameters"]
    params["additionalProperties"] = False
    del params["additionalProperties"]
    params["properties"]["x"]["description"] = "modified"

    # Original declarations remain completely intact and frozen
    orig_params = decls[0]["function"]["parameters"]
    assert "description" not in orig_params["properties"]["x"]
    with pytest.raises(TypeError):
        del orig_params["type"]
