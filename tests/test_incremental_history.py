"""Tests for incremental message history with read-only view."""

from __future__ import annotations

import json
import sys
import tracemalloc

import pytest

from lughus.loop._messages import MessageHistory, _ReadOnlyMessageView, render_context_messages
from lughus.loop import ToolExecutionConfig, agent_loop
from lughus.testing import MockLLM
from lughus import ToolRegistry


# ── helpers ──────────────────────────────────────────────────────────────────


def _old_style_message_list(
    system: str,
    context: str,
    context_items=(),
) -> list[dict]:
    """Reproduce the old _prepare_loop message construction (plain list)."""
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(render_context_messages(context_items))
    messages.append({"role": "user", "content": context})
    return messages


# ── Equivalence: incremental vs. old reconstruction ─────────────────────────


class TestEquivalence:
    """Message sequence from incremental history matches the old reconstruction."""

    def test_initial_messages_match(self) -> None:
        old = _old_style_message_list("You help.", "Hello")
        history = MessageHistory()
        history.append({"role": "system", "content": "You help."})
        history.append({"role": "user", "content": "Hello"})
        assert list(history.view) == old

    def test_with_appended_messages(self) -> None:
        old = _old_style_message_list("sys", "ctx")
        history = MessageHistory()
        for m in old:
            history.append(m)

        # Simulate a tool call round-trip
        assistant_msg = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "greet", "arguments": '{"name":"World"}'},
                }
            ],
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": "c1",
            "content": '{"greeting":"Hello World!"}',
        }
        final_msg = {"role": "assistant", "content": "Done."}

        old.append(assistant_msg)
        old.append(tool_msg)
        old.append(final_msg)

        history.append(assistant_msg)
        history.append(tool_msg)
        history.append(final_msg)

        assert list(history.view) == old

    def test_view_reflects_live_state(self) -> None:
        """View always reflects the current state of the history."""
        history = MessageHistory()
        view = history.view
        assert len(view) == 0

        history.append({"role": "system", "content": "a"})
        assert len(view) == 1
        assert view[0] == {"role": "system", "content": "a"}

        history.append({"role": "user", "content": "b"})
        assert len(view) == 2

    @pytest.mark.asyncio
    async def test_agent_loop_messages_identical(self) -> None:
        """Messages sent to the LLM via incremental history match old behavior."""
        registry = ToolRegistry()

        @registry.tool(
            "greet",
            "Greet by name.",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        def greet(*, name: str, state) -> str:
            return json.dumps({"greeting": f"Hello {name}!"})

        llm = MockLLM(
            [
                [{"id": "c1", "name": "greet", "arguments": {"name": "World"}}],
                "Greeting done.",
            ]
        )
        result = await agent_loop(
            llm,
            system="Greet the user.",
            context="Say hi to World",
            registry=registry,
            tool_names=["greet"],
            state=None,
        )
        assert result == "Greeting done."
        assert result.iterations == 2

        # First LLM call: system + user messages
        first_messages = llm.calls[0]["messages"]
        assert first_messages[0]["role"] == "system"
        assert first_messages[1]["role"] == "user"

        # Second LLM call: system + user + assistant (tool call) + tool result
        second_messages = llm.calls[1]["messages"]
        assert second_messages[0]["role"] == "system"
        assert second_messages[1]["role"] == "user"
        assert second_messages[2]["role"] == "assistant"
        assert "tool_calls" in second_messages[2]
        assert second_messages[3]["role"] == "tool"

    def test_extend_equivalent_to_multiple_appends(self) -> None:
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        h1 = MessageHistory()
        for m in msgs:
            h1.append(m)

        h2 = MessageHistory()
        h2.extend(msgs)

        assert list(h1.view) == list(h2.view)
        assert h1.char_count == h2.char_count


# ── Read-only view immutability ──────────────────────────────────────────────


class TestReadOnlyView:
    """The view returned is not mutable — raises TypeError on mutation attempt."""

    @pytest.fixture
    def view(self) -> _ReadOnlyMessageView:
        history = MessageHistory()
        history.append({"role": "system", "content": "test"})
        history.append({"role": "user", "content": "hello"})
        return history.view

    def test_setitem_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view[0] = {"role": "system", "content": "hacked"}  # type: ignore[index]

    def test_delitem_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            del view[0]  # type: ignore[attr-defined]

    def test_append_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.append({"role": "user", "content": "injected"})

    def test_insert_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.insert(0, {"role": "user", "content": "injected"})

    def test_extend_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.extend([{"role": "user", "content": "injected"}])

    def test_pop_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.pop()

    def test_remove_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.remove(view[0])

    def test_clear_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.clear()

    def test_sort_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.sort()

    def test_reverse_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view.reverse()

    def test_iadd_raises(self, view: _ReadOnlyMessageView) -> None:
        with pytest.raises(TypeError, match="read-only"):
            view += [{"role": "user", "content": "injected"}]  # type: ignore[misc]

    def test_read_operations_work(self, view: _ReadOnlyMessageView) -> None:
        """Read operations (indexing, len, iter, contains, slice) work."""
        assert len(view) == 2
        assert view[0]["role"] == "system"
        assert view[1]["role"] == "user"
        assert view[0] in view
        assert list(view) == [view[0], view[1]]
        assert view[0:2] == [view[0], view[1]]


# ── Incremental token count ─────────────────────────────────────────────────


class TestCharCount:
    """Token count grows incrementally (not recomputed from scratch)."""

    def test_empty_history_char_count(self) -> None:
        history = MessageHistory()
        # Empty list serializes to '[]' = 2 chars
        assert history.char_count == 2
        expected = len(json.dumps([], ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected

    def test_single_message_char_count(self) -> None:
        history = MessageHistory()
        msg = {"role": "system", "content": "You are a helpful assistant."}
        history.append(msg)
        expected = len(json.dumps([msg], ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected

    def test_multiple_messages_char_count(self) -> None:
        history = MessageHistory()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        for m in messages:
            history.append(m)
        expected = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected

    def test_char_count_grows_incrementally(self) -> None:
        """Each append increases char_count by the msg size + separator."""
        history = MessageHistory()
        counts: list[int] = [history.char_count]

        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        for m in messages:
            history.append(m)
            counts.append(history.char_count)

        # Verify monotonic increase
        for i in range(1, len(counts)):
            assert counts[i] > counts[i - 1], "char_count must increase on each append"

        # Verify final matches json.dumps
        expected = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))
        assert counts[-1] == expected

    def test_char_count_with_complex_messages(self) -> None:
        """Char count matches json.dumps for messages containing tool calls."""
        history = MessageHistory()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "call tool"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "greet",
                            "arguments": '{"name":"World"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"greeting":"Hello World!"}',
            },
            {"role": "assistant", "content": "Done."},
        ]
        for m in messages:
            history.append(m)
        expected = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected

    def test_char_count_with_unicode(self) -> None:
        """Char count is correct for messages containing unicode."""
        history = MessageHistory()
        messages = [
            {"role": "system", "content": "Aide en francais."},
            {"role": "user", "content": "Bonjour le monde!"},
        ]
        for m in messages:
            history.append(m)
        expected = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected


# ── Linear allocation growth ────────────────────────────────────────────────


class TestLinearGrowth:
    """Allocation growth is linear, not quadratic."""

    def test_linear_allocation(self) -> None:
        """Appending N messages allocates O(N) total, not O(N^2).

        We measure memory growth for two sizes.  If growth were quadratic,
        doubling N would quadruple memory; linear growth doubles it.
        """
        def _measure(n: int) -> int:
            tracemalloc.start()
            history = MessageHistory()
            for i in range(n):
                history.append(
                    {"role": "user", "content": f"message number {i}"}
                )
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return peak

        small = _measure(500)
        large = _measure(2000)

        # With linear growth, 4x messages should give roughly 4x memory.
        # With quadratic growth it would be ~16x.  Allow up to 6x for
        # allocator overhead and object layout variation.
        ratio = large / small
        assert ratio < 6.0, (
            f"Memory ratio {ratio:.1f}x for 4x messages suggests "
            f"quadratic allocation (small={small}, large={large})"
        )

    def test_no_list_copy_per_iteration(self) -> None:
        """The view shares the backing list; no copy is made per access."""
        history = MessageHistory()
        for i in range(100):
            history.append({"role": "user", "content": f"msg {i}"})

        view = history.view
        # The view's internal data IS the history's internal list (same object)
        assert view._data is history._messages


# ── MessageHistory repr and len ──────────────────────────────────────────────


class TestMessageHistoryMisc:

    def test_len(self) -> None:
        history = MessageHistory()
        assert len(history) == 0
        history.append({"role": "user", "content": "hi"})
        assert len(history) == 1

    def test_repr(self) -> None:
        history = MessageHistory()
        history.append({"role": "user", "content": "hi"})
        r = repr(history)
        assert "MessageHistory" in r
        assert "len=1" in r

    def test_view_equality_with_list(self) -> None:
        history = MessageHistory()
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]
        history.extend(msgs)
        assert history.view == msgs
        assert msgs == list(history.view)

    def test_initial_messages_in_constructor(self) -> None:
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]
        history = MessageHistory(msgs)
        assert list(history.view) == msgs
        expected = len(json.dumps(msgs, ensure_ascii=False, separators=(",", ":")))
        assert history.char_count == expected
