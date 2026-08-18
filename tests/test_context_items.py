"""Real context_items injection into the agent loop.

Replaces tests/test_context_items_not_ignored.py (0.10.2 guard).
"""

from __future__ import annotations

import json
import random

import pytest

from lughus import ToolRegistry
from lughus.context import ContextItem, TrustLevel
from lughus.loop import agent_loop
from lughus.testing import MockLLM


def _make_items() -> list[ContextItem]:
    """Build a small set of context items with distinct trust levels and ids."""
    return [
        ContextItem(
            role="user",
            content="External data from API",
            source="api-gateway",
            trust=TrustLevel.EXTERNAL,
            id="ext-001",
        ),
        ContextItem(
            role="user",
            content="User preference: dark mode",
            source="profile-service",
            trust=TrustLevel.USER,
            id="usr-002",
        ),
        ContextItem(
            role="user",
            content="Tool output: 42",
            source="calculator",
            trust=TrustLevel.TOOL,
            id="tool-003",
        ),
        ContextItem(
            role="user",
            content="System config: max_retries=3",
            source="config",
            trust=TrustLevel.SYSTEM,
            id="sys-004",
        ),
    ]


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool(
        "echo",
        "Echo input.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    def echo(*, text: str, state) -> str:
        return json.dumps({"echo": text})

    return r


# ── Context items appear in messages ────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_items_appear_in_llm_messages(registry: ToolRegistry) -> None:
    """Context items must be present in the messages sent to the LLM."""
    items = _make_items()
    llm = MockLLM(["Acknowledged."])

    await agent_loop(
        llm,
        system="You help.",
        context="What is the answer?",
        registry=registry,
        tool_names=[],
        context_items=items,
    )

    messages = llm.calls[0]["messages"]
    # System, context block, user objective = 3 messages
    assert len(messages) == 3
    context_msg = messages[1]
    assert context_msg["role"] == "user"
    # All four items should appear in the context message
    for item in items:
        assert item.content in context_msg["content"]
        assert item.source in context_msg["content"]
        assert item.trust in context_msg["content"]
        assert item.id in context_msg["content"]


# ── Deterministic ordering ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_is_deterministic_over_100_permutations(
    registry: ToolRegistry,
) -> None:
    """Sort by (trust, id) must produce identical output regardless of input order."""
    items = _make_items()
    reference_llm = MockLLM(["ok"])
    await agent_loop(
        reference_llm,
        system=".",
        context=".",
        registry=registry,
        tool_names=[],
        context_items=items,
    )
    reference = reference_llm.calls[0]["messages"][1]["content"]

    rng = random.Random(42)
    for _ in range(100):
        shuffled = list(items)
        rng.shuffle(shuffled)
        llm = MockLLM(["ok"])
        await agent_loop(
            llm,
            system=".",
            context=".",
            registry=registry,
            tool_names=[],
            context_items=shuffled,
        )
        assert llm.calls[0]["messages"][1]["content"] == reference


# ── Provenance and trust present ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provenance_and_trust_in_output(registry: ToolRegistry) -> None:
    """Each context item must carry its source and trust level in the XML tag."""
    items = _make_items()
    llm = MockLLM(["ok"])

    await agent_loop(
        llm,
        system=".",
        context=".",
        registry=registry,
        tool_names=[],
        context_items=items,
    )

    content = llm.calls[0]["messages"][1]["content"]
    for item in items:
        assert f'source="{item.source}"' in content
        assert f'trust="{item.trust}"' in content
        assert f'id="{item.id}"' in content


# ── Role is always user, never system ───────────────────────────────────────


@pytest.mark.asyncio
async def test_context_items_use_role_user_never_system(
    registry: ToolRegistry,
) -> None:
    """Security: context items must use role 'user', not 'system'."""
    items = _make_items()
    llm = MockLLM(["ok"])

    await agent_loop(
        llm,
        system=".",
        context=".",
        registry=registry,
        tool_names=[],
        context_items=items,
    )

    messages = llm.calls[0]["messages"]
    # Only the first message should be system
    assert messages[0]["role"] == "system"
    # The context message must be user
    context_msg = messages[1]
    assert context_msg["role"] == "user"
    # No context item content should appear in the system message
    for item in items:
        assert item.content not in messages[0]["content"]


# ── Prefix stability across turns ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_prefix_identical_between_turn_1_and_turn_3(
    registry: ToolRegistry,
) -> None:
    """The cacheable prefix (system + context) must be byte-identical across
    all turns, even after tool calls mutate the message history."""
    items = _make_items()

    # Two tool-call rounds, then a text response = 3 LLM turns.
    llm = MockLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "ping"}}],
            [{"id": "c2", "name": "echo", "arguments": {"text": "pong"}}],
            "Done.",
        ]
    )

    await agent_loop(
        llm,
        system="You help.",
        context="Do two echoes.",
        registry=registry,
        tool_names=["echo"],
        context_items=items,
    )

    # Extract the prefix (system + context messages) from turn 1 and turn 3.
    turn_1_msgs = llm.calls[0]["messages"]
    turn_3_msgs = llm.calls[2]["messages"]

    # The prefix is the first 2 messages (system + context block).
    prefix_len = 2  # system + context
    prefix_turn_1 = turn_1_msgs[:prefix_len]
    prefix_turn_3 = turn_3_msgs[:prefix_len]

    assert prefix_turn_1 == prefix_turn_3, "Cacheable prefix diverged between turn 1 and turn 3"


# ── Empty context_items is a no-op ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_context_items_produces_no_extra_messages(
    registry: ToolRegistry,
) -> None:
    """When context_items is empty, messages should be [system, user] only."""
    llm = MockLLM(["ok"])

    await agent_loop(
        llm,
        system="sys",
        context="obj",
        registry=registry,
        tool_names=[],
        context_items=(),
    )

    messages = llm.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "obj"}
