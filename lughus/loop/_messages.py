"""Message history with read-only view and XML context rendering.

Security decision: context items use role ``user``, never ``system``.
Variable-trust content must not inherit system authority.

Sort order ``(trust, id)`` is deterministic — critical for prefix
stability (rule A1: the cacheable prefix must be byte-identical across
turns).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from typing import Any, overload
from xml.sax.saxutils import escape

from ..context import ContextItem


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
    """Append-only message list with incremental char counting and a read-only view.

    The char count tracks the exact value that ``json.dumps(messages,
    ensure_ascii=False, separators=(",",":"))`` would produce, but is
    maintained incrementally so that callers never pay O(n) to recompute
    it from scratch.  This is the preparation step for W3-03 token
    budgets.

    The :attr:`view` property returns a :class:`~collections.abc.Sequence`
    that shares the backing list but raises ``TypeError`` on any mutation
    attempt, protecting the canonical history from accidental corruption.
    """

    __slots__ = ("_messages", "_char_count", "_view")

    def __init__(self, initial: Iterable[dict[str, Any]] | None = None) -> None:
        self._messages: list[dict[str, Any]] = []
        self._char_count: int = 2  # accounts for enclosing '[]'
        self._view = _ReadOnlyMessageView(self._messages)
        if initial is not None:
            for msg in initial:
                self.append(msg)

    @staticmethod
    def _msg_chars(msg: dict[str, Any]) -> int:
        """JSON char count for a single message dict (compact separators)."""
        return len(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))

    def append(self, msg: dict[str, Any]) -> None:
        """Append *msg* and update the incremental char count."""
        if self._messages:
            self._char_count += 1  # comma separator between elements
        self._char_count += self._msg_chars(msg)
        self._messages.append(msg)

    def extend(self, msgs: Iterable[dict[str, Any]]) -> None:
        """Append every message in *msgs*."""
        for msg in msgs:
            self.append(msg)

    @property
    def view(self) -> _ReadOnlyMessageView:
        """Read-only view sharing the backing list — mutation raises TypeError."""
        return self._view

    @property
    def char_count(self) -> int:
        """Exact JSON char count equivalent to ``len(json.dumps(list, ...))``."""
        return self._char_count

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return f"MessageHistory(len={len(self._messages)}, chars={self._char_count})"


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
