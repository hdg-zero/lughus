"""Events emitted by an agent workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    """Intermediate progress (shown as A2A working status)."""

    text: str


@dataclass
class Artifact:
    """A file produced by the agent."""

    data: bytes
    mime_type: str
    name: str


@dataclass
class CompletionEvent:
    """End of processing — text response and optional artifacts."""

    text: str
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
