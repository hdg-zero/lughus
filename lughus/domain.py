"""Versioned domain records for observable agent execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

SCHEMA_VERSION = "1.0"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class EventVisibility(StrEnum):
    INTERNAL = "internal"
    MODEL = "model"
    PUBLIC = "public"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class RunEvent:
    type: str
    run_id: str
    sequence: int
    data: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("evt"))
    step_id: str | None = None
    causation_id: str | None = None
    visibility: EventVisibility = EventVisibility.INTERNAL
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("Event sequence cannot be negative")
        if not self.type or not self.run_id:
            raise ValueError("Event type and run_id are required")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["visibility"] = self.visibility.value
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunEvent":
        data = dict(value)
        data["visibility"] = EventVisibility(data.get("visibility", "internal"))
        return cls(**data)


@dataclass(frozen=True, slots=True)
class Run:
    objective: str
    run_id: str = field(default_factory=lambda: new_id("run"))
    status: RunStatus = RunStatus.PENDING
    version: int = 0
    context_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        if not self.objective:
            raise ValueError("Run objective is required")
        if self.version < 0:
            raise ValueError("Run version cannot be negative")
