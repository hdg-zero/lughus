"""Context selection with explicit provenance and trust."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TrustLevel(StrEnum):
    SYSTEM = "system"
    USER = "user"
    EXTERNAL = "external"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ContextItem:
    role: str
    content: str
    source: str
    trust: TrustLevel
    sensitive: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    id: str = ""

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class ContextWindow:
    items: tuple[ContextItem, ...]
    omitted: int
    total_characters: int

    def messages(self) -> list[dict[str, str]]:
        return [{"role": item.role, "content": item.content} for item in self.items]


class ContextManager:
    """Preserve trusted system items, then select the newest complete items."""

    def __init__(self, max_characters: int) -> None:
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self.max_characters = max_characters

    def select(self, values: Iterable[ContextItem]) -> ContextWindow:
        items = tuple(values)
        system = [item for item in items if item.trust == TrustLevel.SYSTEM]
        if sum(item.size for item in system) > self.max_characters:
            raise ValueError("System context alone exceeds the context budget")
        selected = list(system)
        used_ids = {id(item) for item in selected}
        remaining = self.max_characters - sum(item.size for item in selected)
        tail: list[ContextItem] = []
        for item in reversed(items):
            if id(item) in used_ids:
                continue
            if item.size <= remaining:
                tail.append(item)
                remaining -= item.size
        selected.extend(reversed(tail))
        return ContextWindow(
            tuple(selected), len(items) - len(selected), sum(item.size for item in selected)
        )
