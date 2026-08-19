"""token context budget with atomic groups."""

from __future__ import annotations

import pytest

from lughus.errors import ContextBudgetExceeded
from lughus.loop._messages import (
    MessageHistory,
    _build_groups,
    estimate_tokens,
    prune_history,
)

# ── Token estimation ──────────────────────────────────────────────────────────


def test_estimate_tokens_empty() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_short() -> None:
    assert estimate_tokens("hi") >= 1


def test_estimate_tokens_conservative() -> None:
    """estimate_tokens should never under-estimate by more than ~15% vs 4-char rule."""
    text = "The quick brown fox jumps over the lazy dog. " * 20
    estimated = estimate_tokens(text)
    chars_per_4 = len(text) // 4
    assert estimated >= chars_per_4 * 0.85


# ── Atomic groups ─────────────────────────────────────────────────────────────


def _make_history() -> list[dict]:
    """Build a message list with tool call pairs."""
    return [
        {"role": "system", "content": "You help."},
        {"role": "user", "content": "Do stuff."},
        # Group 1: assistant + tool
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "a", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": '{"ok":true,"result":"r1"}'},
        # Group 2: assistant + 2 tools
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                {"id": "tc3", "type": "function", "function": {"name": "c", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "tc2", "content": '{"ok":true,"result":"r2"}'},
        {"role": "tool", "tool_call_id": "tc3", "content": '{"ok":true,"result":"r3"}'},
        # Group 3: standalone assistant
        {"role": "assistant", "content": "Done."},
    ]


def test_build_groups_identifies_atomic_groups() -> None:
    msgs = _make_history()
    groups = _build_groups(msgs, prefix_len=2)
    assert len(groups) == 3
    assert groups[0] == [2, 3]  # assistant + 1 tool
    assert groups[1] == [4, 5, 6]  # assistant + 2 tools
    assert groups[2] == [7]  # standalone


def test_pruning_never_splits_tool_pairs() -> None:
    """No pruning ever separates a tool_call from its tool_result."""
    msgs = _make_history()
    pruned = prune_history(msgs, max_tokens=200, prefix_len=2)
    assert pruned > 0
    # Verify: every assistant with tool_calls has all its tool results
    for i, msg in enumerate(msgs):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tc_ids = {tc["id"] for tc in msg["tool_calls"]}
            following_tool_ids = set()
            for j in range(i + 1, len(msgs)):
                if msgs[j].get("role") == "tool":
                    following_tool_ids.add(msgs[j]["tool_call_id"])
                else:
                    break
            assert tc_ids == following_tool_ids


def test_prefix_never_pruned() -> None:
    """System and user messages (prefix) are never pruned."""
    msgs = _make_history()
    prune_history(msgs, max_tokens=200, prefix_len=2)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_prune_oldest_first() -> None:
    """Pruning removes the oldest groups first."""
    msgs = _make_history()
    original_last = msgs[-1].copy()
    prune_history(msgs, max_tokens=200, prefix_len=2)
    # The last message (standalone "Done.") should survive longest
    if len(msgs) > 2:
        assert msgs[-1] == original_last


def test_single_group_exceeds_budget_raises() -> None:
    """A single atomic group larger than the budget raises ContextBudgetExceeded."""
    big_content = "x" * 50000
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "obj"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "a", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": big_content},
    ]
    with pytest.raises(ContextBudgetExceeded):
        prune_history(msgs, max_tokens=100, prefix_len=2)


def test_no_pruning_when_under_budget() -> None:
    """No pruning occurs when total tokens are under the budget."""
    msgs = _make_history()
    pruned = prune_history(msgs, max_tokens=999999, prefix_len=2)
    assert pruned == 0
    assert len(msgs) == 8


def test_empty_history_no_pruning() -> None:
    """Empty non-prefix history needs no pruning."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "obj"},
    ]
    pruned = prune_history(msgs, max_tokens=999, prefix_len=2)
    assert pruned == 0


def test_message_history_prune_method() -> None:
    """MessageHistory.prune() delegates correctly."""
    h = MessageHistory()
    h.append({"role": "system", "content": "sys"})
    h.append({"role": "user", "content": "obj"})
    h.append({"role": "assistant", "content": "x" * 500})
    h.append({"role": "assistant", "content": "y" * 500})

    pruned = h.prune(max_tokens=200, prefix_len=2)
    assert pruned > 0
    assert len(h) >= 2  # prefix always survives


def test_many_tool_pairs_no_split() -> None:
    """With 20 tool pairs, pruning never splits any pair."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "obj"},
    ]
    for i in range(20):
        tc_id = f"tc{i}"
        msgs.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": f"t{i}", "arguments": "{}"},
                    }
                ],
            }
        )
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f'{{"ok":true,"result":"result_{i}"}}',
            }
        )

    prune_history(msgs, max_tokens=200, prefix_len=2)
    # Verify integrity: every remaining assistant with tool_calls has its tool results
    for i, msg in enumerate(msgs):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tc_ids = {tc["id"] for tc in msg["tool_calls"]}
            following = set()
            for j in range(i + 1, len(msgs)):
                if msgs[j].get("role") == "tool":
                    following.add(msgs[j]["tool_call_id"])
                else:
                    break
            assert tc_ids == following, f"Split tool pair at index {i}"
