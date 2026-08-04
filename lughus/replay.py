"""Portable, integrity-checked replay bundles."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .domain import RunEvent

REPLAY_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class ReplayCapturePolicy:
    redacted_keys: frozenset[str] = frozenset(
        {"password", "secret", "token", "api_key", "authorization"}
    )
    max_string_characters: int = 100_000

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): (
                    "[REDACTED]" if str(key).lower() in self.redacted_keys else self.sanitize(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.sanitize(item) for item in value]
        if isinstance(value, str) and len(value) > self.max_string_characters:
            return value[: self.max_string_characters] + "…[TRUNCATED]"
        return value


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
    signature: str = ""

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

    def seal(self, *, signing_key: bytes | None = None) -> ReplayBundle:
        digest = hashlib.sha256(_canonical(self.payload())).hexdigest()
        signature = (
            hmac.new(signing_key, digest.encode(), hashlib.sha256).hexdigest()
            if signing_key
            else ""
        )
        return ReplayBundle(
            **self.payload_without_events(),
            events=self.events,
            calls=self.calls,
            integrity=digest,
            signature=signature,
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

    def verify_signature(self, signing_key: bytes) -> bool:
        expected = hmac.new(signing_key, self.integrity.encode(), hashlib.sha256).hexdigest()
        return (
            self.verify() and bool(self.signature) and hmac.compare_digest(expected, self.signature)
        )

    def to_json(self) -> str:
        if not self.verify():
            raise ValueError("Replay bundle must be sealed and valid")
        value = self.payload()
        value["integrity"] = self.integrity
        value["signature"] = self.signature
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
