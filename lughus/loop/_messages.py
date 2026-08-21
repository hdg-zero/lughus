"""Message history with read-only view, XML context rendering, and token-budget pruning.

Security decision: context items use role ``user``, never ``system``.
Variable-trust content must not inherit system authority.

Sort order ``(trust, id)`` is deterministic — critical for prefix
stability (rule A1: the cacheable prefix must be byte-identical across
turns).

token-based context budgets with atomic groups.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator, Sequence
from typing import Any, overload
from xml.sax.saxutils import escape

from ..core.context import ContextItem
from ..core.errors import ContextBudgetExceeded

_logger = logging.getLogger(__name__)


# ── Read-only view ────────────────────────────────────────────────────────────


class _ReadOnlyMessageView(Sequence[dict[str, Any]]):
    """Immutable view over an internal message list.

    Delegates all read operations to the backing list.  Any mutation
    attempt raises ``TypeError`` so that callers sharing this view
    cannot corrupt the canonical history.
    """

    __slots__ = ("_data",)

    def __init__(self, data: list[dict[str, Any]]) -> None:
        self._data = data

    # ── Sequence interface ────────────────────────────────────────────

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...
    @overload
    def __getitem__(self, index: slice) -> list[dict[str, Any]]: ...
    def __getitem__(self, index: int | slice) -> dict[str, Any] | list[dict[str, Any]]:
        return self._data[index]

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._data)

    def __contains__(self, value: object) -> bool:
        return value in self._data

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._data!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _ReadOnlyMessageView):
            return self._data == other._data
        if isinstance(other, list):
            return self._data == other
        return NotImplemented

    # ── Mutation guards ───────────────────────────────────────────────

    def __setitem__(self, index: Any, value: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def __delitem__(self, index: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def __iadd__(self, other: Any) -> Any:
        raise TypeError("MessageHistory view is read-only")

    def append(self, value: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def insert(self, index: Any, value: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def extend(self, values: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def pop(self, index: int = -1) -> Any:
        raise TypeError("MessageHistory view is read-only")

    def remove(self, value: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def clear(self) -> None:
        raise TypeError("MessageHistory view is read-only")

    def sort(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("MessageHistory view is read-only")

    def reverse(self) -> None:
        raise TypeError("MessageHistory view is read-only")


# ── Incremental message history ──────────────────────────────────────────────


class MessageHistory:
    """Append-only message list with a read-only view.

    The :attr:`view` property returns a :class:`~collections.abc.Sequence`
    that shares the backing list but raises ``TypeError`` on any mutation
    attempt, protecting the canonical history from accidental corruption.
    """

    __slots__ = ("_messages", "_view")

    def __init__(self, initial: Iterable[dict[str, Any]] | None = None) -> None:
        self._messages: list[dict[str, Any]] = []
        self._view = _ReadOnlyMessageView(self._messages)
        if initial is not None:
            for msg in initial:
                self.append(msg)

    def append(self, msg: dict[str, Any]) -> None:
        """Append *msg* to the history."""
        self._messages.append(msg)

    def extend(self, msgs: Iterable[dict[str, Any]]) -> None:
        """Append every message in *msgs*."""
        for msg in msgs:
            self.append(msg)

    @property
    def view(self) -> _ReadOnlyMessageView:
        """Read-only view sharing the backing list — mutation raises TypeError."""
        return self._view

    def __len__(self) -> int:
        return len(self._messages)

    def prune(self, max_tokens: int, prefix_len: int, model: str | None = None) -> int:
        """Drop oldest non-prefix atomic groups until estimated tokens fit *max_tokens*.

        Returns the number of groups pruned.  Raises :class:`ContextBudgetExceeded`
        if a single atomic group exceeds the entire budget.
        """
        return prune_history(self._messages, max_tokens, prefix_len, model=model)

    def __repr__(self) -> str:
        return f"MessageHistory(len={len(self._messages)})"


# ── Token estimation ────────────────────────────────────────────────────────


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Return a token estimate for *text*.

    When *model* is provided, delegates to ``litellm.token_counter`` for an
    accurate count.  Falls back to ``len(text) // 4`` (industry-standard
    approximation of ~4 chars per token for English prose).
    """
    if not text:
        return 0
    if model is not None:
        try:
            import litellm

            return max(1, litellm.token_counter(model=model, text=text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _message_tokens(msg: dict[str, Any], model: str | None = None) -> int:
    """Estimate the token cost of a single message dict."""
    serialized = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
    return estimate_tokens(serialized, model=model)


# ── Atomic groups ────────────────────────────────────────────────────────────


def _build_groups(messages: list[dict[str, Any]], prefix_len: int) -> list[list[int]]:
    """Identify atomic message groups in *messages* starting after *prefix_len*.

    An assistant message with ``tool_calls`` plus all subsequent ``tool`` role
    messages (matching those calls) form an **atomic group** that must never be
    split during pruning.  A standalone assistant or user message is its own
    group.

    Returns a list of groups, each group being a list of message indices.
    """
    groups: list[list[int]] = []
    i = prefix_len
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Start of an atomic group: assistant + all tool results
            group = [i]
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                group.append(i)
                i += 1
            groups.append(group)
        else:
            groups.append([i])
            i += 1
    return groups


# ── Pruning ──────────────────────────────────────────────────────────────────


def prune_history(
    messages: list[dict[str, Any]],
    max_tokens: int,
    prefix_len: int,
    model: str | None = None,
) -> int:
    """Remove oldest non-prefix atomic groups from *messages* until under budget.

    *messages* is mutated in-place.  *prefix_len* messages at the start are
    never pruned (system prompt, context items, user objective).

    Returns the number of groups pruned.

    Raises :class:`ContextBudgetExceeded` if a single atomic group is larger
    than the entire *max_tokens* budget.
    """
    total_tokens = sum(_message_tokens(m, model=model) for m in messages)
    if total_tokens <= max_tokens:
        return 0

    groups = _build_groups(messages, prefix_len)
    if not groups:
        return 0

    # Check if any single group exceeds the budget on its own
    prefix_tokens = sum(_message_tokens(messages[i], model=model) for i in range(prefix_len))
    available = max_tokens - prefix_tokens
    for group in groups:
        group_tokens = sum(_message_tokens(messages[idx], model=model) for idx in group)
        if group_tokens > available:
            raise ContextBudgetExceeded(
                f"A single atomic group ({group_tokens} estimated tokens) "
                f"exceeds the context budget ({available} tokens available "
                f"after {prefix_tokens} prefix tokens)"
            )

    # Prune oldest groups first
    pruned_count = 0
    indices_to_remove: list[int] = []
    for group in groups:
        if total_tokens <= max_tokens:
            break
        group_tokens = sum(_message_tokens(messages[idx], model=model) for idx in group)
        indices_to_remove.extend(group)
        total_tokens -= group_tokens
        pruned_count += 1

    # Remove indices in reverse order to preserve positions
    for idx in sorted(indices_to_remove, reverse=True):
        del messages[idx]

    if pruned_count > 0:
        _logger.debug(
            "Pruned %d atomic group(s); estimated tokens now %d",
            pruned_count,
            total_tokens,
        )

    return pruned_count


# ── Context rendering ────────────────────────────────────────────────────────


def render_context_messages(items: Sequence[ContextItem]) -> list[dict[str, str]]:
    """Return a list of user-role message dicts wrapping *items* in XML tags.

    Each item becomes::

        <context source="..." trust="..." id="...">content</context>

    Items are sorted by ``(trust, id)`` for deterministic ordering.
    An empty sequence returns an empty list.
    """
    if not items:
        return []

    sorted_items = sorted(items, key=lambda ci: (ci.trust, ci.id))

    parts: list[str] = []
    for ci in sorted_items:
        tag = (
            f'<context source="{escape(ci.source)}" '
            f'trust="{escape(ci.trust)}" '
            f'id="{escape(ci.id)}">'
            f"{escape(ci.content)}"
            f"</context>"
        )
        parts.append(tag)

    return [{"role": "user", "content": "\n".join(parts)}]
