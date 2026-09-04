"""Events emitted by an agent workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    """Intermediate progress update emitted as an A2A working status."""

    text: str


@dataclass
class Artifact:
    """Binary or text artifact produced by an agent."""

    data: bytes
    mime_type: str
    name: str


@dataclass
class CompletionEvent:
    """Terminal event signalling successful completion with output text and artifacts."""

    text: str
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
