"""Portable, integrity-checked replay bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .domain import RunEvent

REPLAY_SCHEMA_VERSION = "1.0"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True, slots=True)
class RecordedCall:
    kind: str
    request_hash: str
    response: Mapping[str, Any]
    sequence: int


@dataclass(frozen=True, slots=True)
class ReplayBundle:
    framework_version: str
    run_id: str
    configuration: Mapping[str, Any]
    events: tuple[RunEvent, ...]
    calls: tuple[RecordedCall, ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = REPLAY_SCHEMA_VERSION
    integrity: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "framework_version": self.framework_version,
            "run_id": self.run_id,
            "configuration": dict(self.configuration),
            "events": [event.to_dict() for event in self.events],
            "calls": [asdict(call) for call in self.calls],
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    def seal(self) -> ReplayBundle:
        digest = hashlib.sha256(_canonical(self.payload())).hexdigest()
        return ReplayBundle(
            **self.payload_without_events(), events=self.events, calls=self.calls, integrity=digest
        )

    def payload_without_events(self) -> dict[str, Any]:
        return {
            "framework_version": self.framework_version,
            "run_id": self.run_id,
            "configuration": self.configuration,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    def verify(self) -> bool:
        return (
            bool(self.integrity)
            and hashlib.sha256(_canonical(self.payload())).hexdigest() == self.integrity
        )

    def to_json(self) -> str:
        if not self.verify():
            raise ValueError("Replay bundle must be sealed and valid")
        value = self.payload()
        value["integrity"] = self.integrity
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> ReplayBundle:
        value = json.loads(raw)
        events = tuple(RunEvent.from_dict(event) for event in value.pop("events"))
        calls = tuple(RecordedCall(**call) for call in value.pop("calls", ()))
        bundle = cls(events=events, calls=calls, **value)
        if not bundle.verify():
            raise ValueError("Replay bundle integrity check failed")
        return bundle
