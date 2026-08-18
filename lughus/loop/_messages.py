"""Render context items as user messages with XML provenance tags.

Security decision: context items use role ``user``, never ``system``.
Variable-trust content must not inherit system authority.

Sort order ``(trust, id)`` is deterministic — critical for prefix
stability (rule A1: the cacheable prefix must be byte-identical across
turns).
"""

from __future__ import annotations

from collections.abc import Sequence
from xml.sax.saxutils import escape

from ..context import ContextItem


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
