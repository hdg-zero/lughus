"""Versioned domain records for observable agent execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


def canonical_json(data: Any) -> str:
    """Return compact, sorted UTF-8 JSON representation for deterministic hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(data: Any) -> str:
    """Compute deterministic SHA-256 hex digest of a JSON-serializable structure."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


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


def _usage_get(usage: Any, key: str, default: Any = 0) -> Any:
    if isinstance(usage, dict):
        return usage.get(key, default)
    return getattr(usage, key, default)


def _extract_usage(usage: Any) -> tuple[int, int, int]:
    """Return (prompt_tokens, completion_tokens, cached_tokens).

    Normalizes across provider payload shapes surfaced by LiteLLM:
    OpenAI (``prompt_tokens``/``completion_tokens``), Anthropic
    (``input_tokens``/``output_tokens``/``cache_read_input_tokens``),
    and Gemini (``prompt_token_count``/``candidates_token_count``/
    ``cached_content_token_count``).
    """
    prompt = (
        _usage_get(usage, "prompt_tokens", None)
        or _usage_get(usage, "input_tokens", None)
        or _usage_get(usage, "prompt_token_count", None)
        or 0
    )
    completion = (
        _usage_get(usage, "completion_tokens", None)
        or _usage_get(usage, "output_tokens", None)
        or _usage_get(usage, "candidates_token_count", None)
        or 0
    )
    cached = 0
    details = _usage_get(usage, "prompt_tokens_details", None)
    if details:
        cached += _usage_get(details, "cached_tokens", 0) or 0
    alias_read = max(
        _usage_get(usage, "_cache_read_input_tokens", 0) or 0,
        _usage_get(usage, "cache_read_input_tokens", 0) or 0,
    )
    cached += alias_read
    cached += _usage_get(usage, "cached_content_token_count", 0) or 0
    return prompt, completion, cached


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
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
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
    def from_dict(cls, value: Mapping[str, Any]) -> RunEvent:
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
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    usage: Usage = field(default_factory=Usage)
    tenant_id: str = "default"
    principal_id: str = "anonymous"

    def __post_init__(self) -> None:
        if not self.objective:
            raise ValueError("Run objective is required")
        if self.version < 0:
            raise ValueError("Run version cannot be negative")
        if not self.tenant_id or not self.principal_id:
            raise ValueError("Run tenant and principal are required")
