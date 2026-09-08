"""SQLite reference backend: atomic lifecycle, execution journal and approvals.

Local filesystem only, one database per trust boundary. WAL + FULL synchronous,
optimistic run versions and explicit execution ownership. No automatic lease
expiry: a slow worker is never mistaken for a dead worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from ..core.domain import Run, RunEvent, RunStatus, Usage
from .store import Checkpoint, ConcurrentUpdateError

T = TypeVar("T")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _run(value: str) -> Run:
    data = json.loads(value)
    data["status"] = RunStatus(data["status"])
    data["usage"] = Usage(**data["usage"])
    return Run(**data)


class SQLiteStore:
    durable = True
    shared_across_replicas = False  # SQLite is not a distributed storage service
    atomic_updates = True
    supports_event_log = True
    supports_idempotency = True

    def __init__(self, path: str | Path, *, max_snapshot_bytes: int = 4_000_000) -> None:
        if str(path) == ":memory:" or max_snapshot_bytes <= 0:
            raise ValueError("Use a filesystem path and positive snapshot limit")
        self.path = str(Path(path).resolve())
        self.max_snapshot_bytes = max_snapshot_bytes
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        conn = self._connect()
        try:
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if schema_version not in {0, 21}:
                raise ValueError("Unsupported database schema; migrate explicitly")
            conn.execute("PRAGMA user_version=21")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    run_id TEXT PRIMARY KEY,
                    owner TEXT,
                    snapshot TEXT NOT NULL,
                    budget TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS actions (
                    run_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    PRIMARY KEY(run_id, call_id)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS approvals_proposal ON approvals(run_id, digest);
                CREATE TABLE IF NOT EXISTS reconciliations (
                    id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    call_id TEXT,
                    actor TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
            """)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    async def _call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        def transaction() -> T:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                value = fn(conn)
                conn.commit()
                return value
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

        # Do not abandon an in-flight commit before reporting cancellation.
        task = asyncio.create_task(asyncio.to_thread(transaction))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await asyncio.shield(task)
            raise

    @staticmethod
    def _owner(conn: sqlite3.Connection, run_id: str, owner: str) -> None:
        row = conn.execute("SELECT owner FROM executions WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[0] != owner:
            raise ConcurrentUpdateError("Execution ownership lost")

    @staticmethod
    def _event(conn: sqlite3.Connection, event: RunEvent) -> None:
        row = conn.execute(
            "SELECT MAX(sequence) FROM events WHERE run_id=?", (event.run_id,)
        ).fetchone()
        if row[0] is not None and event.sequence <= row[0]:
            raise ConcurrentUpdateError("Event sequence is not monotonic")
        conn.execute(
            "INSERT INTO events VALUES (?,?,?)",
            (event.run_id, event.sequence, _json(event.to_dict())),
        )

    async def get(self, run_id: str) -> Run | None:
        def op(conn: sqlite3.Connection) -> Run | None:
            row = conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            return _run(row[0]) if row else None

        return await self._call(op)

    async def create(self, run: Run) -> None:
        await self._call(
            lambda conn: conn.execute(
                "INSERT INTO runs VALUES (?,?,?)", (run.run_id, run.version, _json(asdict(run)))
            )
        )

    async def update_status(self, run_id: str, expected_version: int, status: RunStatus) -> Run:
        return await self._call(lambda conn: self._update(conn, run_id, expected_version, status))

    @staticmethod
    def _update(conn: sqlite3.Connection, run_id: str, version: int, status: RunStatus) -> Run:
        row = conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ConcurrentUpdateError("Run not found")
        current = _run(row[0])
        if current.version != version or current.status.terminal:
            raise ConcurrentUpdateError("Run version changed or already terminal")
        updated = replace(current, version=version + 1, status=status)
        conn.execute(
            "UPDATE runs SET version=?,data=? WHERE id=?",
            (updated.version, _json(asdict(updated)), run_id),
        )
        return updated

    async def append(self, event: RunEvent) -> None:
        await self._call(lambda conn: self._event(conn, event))

    async def read(self, run_id: str, after_sequence: int = -1) -> tuple[RunEvent, ...]:
        return await self._call(
            lambda conn: tuple(
                RunEvent.from_dict(json.loads(row[0]))
                for row in conn.execute(
                    "SELECT data FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
                    (run_id, after_sequence),
                )
            )
        )

    async def latest(self, run_id: str) -> Checkpoint | None:
        def op(conn: sqlite3.Connection) -> Checkpoint | None:
            row = conn.execute("SELECT data FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
            return Checkpoint(**json.loads(row[0])) if row else None

        return await self._call(op)

    async def save(self, checkpoint: Checkpoint, expected_version: int | None) -> None:
        def op(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT version FROM checkpoints WHERE run_id=?", (checkpoint.run_id,)
            ).fetchone()
            if (row[0] if row else None) != expected_version:
                raise ConcurrentUpdateError("Checkpoint version changed")
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)",
                (checkpoint.run_id, checkpoint.version, _json(asdict(checkpoint))),
            )

        await self._call(op)

    async def create_transition(self, run: Run, event: RunEvent, checkpoint: Checkpoint) -> None:
        def op(conn: sqlite3.Connection) -> None:
            if (
                event.run_id != run.run_id
                or checkpoint.run_id != run.run_id
                or checkpoint.sequence != event.sequence
            ):
                raise ValueError("Transition identities must agree")
            conn.execute(
                "INSERT INTO runs VALUES (?,?,?)", (run.run_id, run.version, _json(asdict(run)))
            )
            self._event(conn, event)
            conn.execute(
                "INSERT INTO checkpoints VALUES (?,?,?)",
                (run.run_id, checkpoint.version, _json(asdict(checkpoint))),
            )

        await self._call(op)

    async def commit_transition(
        self,
        *,
        run_id: str,
        expected_version: int,
        status: RunStatus,
        event: RunEvent,
        checkpoint: Checkpoint,
    ) -> Run:
        def op(conn: sqlite3.Connection) -> Run:
            if (
                event.run_id != run_id
                or checkpoint.run_id != run_id
                or checkpoint.sequence != event.sequence
            ):
                raise ValueError("Transition identities must agree")
            updated = self._update(conn, run_id, expected_version, status)
            self._event(conn, event)
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)",
                (run_id, checkpoint.version, _json(asdict(checkpoint))),
            )
            return updated

        return await self._call(op)

    async def open_execution(
        self, run_id: str, owner: str, snapshot: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        def op(conn: sqlite3.Connection) -> dict[str, Any]:
            row = conn.execute(
                "SELECT owner,snapshot FROM executions WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                if snapshot is None:
                    raise ValueError("No resumable execution snapshot")
                encoded = _json(snapshot)
                if len(encoded.encode()) > self.max_snapshot_bytes:
                    raise ValueError("Execution snapshot exceeds limit")
                conn.execute(
                    "INSERT INTO executions(run_id,owner,snapshot) VALUES (?,?,?)",
                    (run_id, owner, encoded),
                )
                return cast(dict[str, Any], json.loads(encoded))
            if row[0] is not None:
                raise ConcurrentUpdateError(
                    "Execution has an owner; stop/recover its worker before resuming"
                )
            if snapshot is not None:
                raise ConcurrentUpdateError("Execution already exists")
            conn.execute("UPDATE executions SET owner=? WHERE run_id=?", (owner, run_id))
            return cast(dict[str, Any], json.loads(row[1]))

        return await self._call(op)

    async def snapshot_execution(
        self, run_id: str, owner: str, snapshot: Mapping[str, Any]
    ) -> None:
        encoded = _json(snapshot)
        if len(encoded.encode()) > self.max_snapshot_bytes:
            raise ValueError("Execution snapshot exceeds limit")

        def op(conn: sqlite3.Connection) -> None:
            self._owner(conn, run_id, owner)
            conn.execute("UPDATE executions SET snapshot=? WHERE run_id=?", (encoded, run_id))

        await self._call(op)

    async def release_execution(self, run_id: str, owner: str) -> None:
        def op(conn: sqlite3.Connection) -> None:
            self._owner(conn, run_id, owner)
            conn.execute("UPDATE executions SET owner=NULL WHERE run_id=?", (run_id,))

        await self._call(op)

    async def execution_owner(self, run_id: str) -> str | None:
        def op(conn: sqlite3.Connection) -> str | None:
            row = conn.execute("SELECT owner FROM executions WHERE run_id=?", (run_id,)).fetchone()
            return row[0] if row else None

        return await self._call(op)

    async def recover_execution(
        self, run_id: str, expected_owner: str, *, actor: str, evidence: str
    ) -> None:
        """Operator-only: caller MUST have terminated the previous worker first.

        There is no automatic lease timeout. Evidence is a required audit note,
        not a machine-verifiable proof that an external worker was terminated.
        """
        if not actor or not evidence:
            raise ValueError("Recovery actor and evidence are required")

        def op(conn: sqlite3.Connection) -> None:
            self._owner(conn, run_id, expected_owner)
            conn.execute("UPDATE executions SET owner=NULL WHERE run_id=?", (run_id,))
            conn.execute(
                "INSERT INTO reconciliations(run_id,actor,evidence,occurred_at) VALUES (?,?,?,?)",
                (run_id, actor, evidence, datetime.now(UTC).isoformat()),
            )

        await self._call(op)

    async def action(
        self, run_id: str, owner: str, call_id: str, fingerprint: str
    ) -> tuple[str, str | None] | None:
        def op(conn: sqlite3.Connection) -> tuple[str, str | None] | None:
            self._owner(conn, run_id, owner)
            row = conn.execute(
                "SELECT fingerprint,status,result FROM actions WHERE run_id=? AND call_id=?",
                (run_id, call_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] != fingerprint:
                raise ValueError("Invocation identity or tool contract changed")
            return row[1], row[2]

        return await self._call(op)

    async def start_action(self, run_id: str, owner: str, call_id: str, fingerprint: str) -> None:
        def op(conn: sqlite3.Connection) -> None:
            self._owner(conn, run_id, owner)
            conn.execute(
                "INSERT INTO actions VALUES (?,?,?,?,NULL)",
                (run_id, call_id, fingerprint, "started"),
            )

        await self._call(op)

    async def complete_action(self, run_id: str, owner: str, call_id: str, result: str) -> None:
        def op(conn: sqlite3.Connection) -> None:
            self._owner(conn, run_id, owner)
            cursor = conn.execute(
                "UPDATE actions SET status='completed',result=? "
                "WHERE run_id=? AND call_id=? AND status='started'",
                (result, run_id, call_id),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError("No started action to complete")

        await self._call(op)

    async def reconcile_action(
        self,
        run_id: str,
        call_id: str,
        *,
        actor: str,
        evidence: str,
        result: str | None = None,
        confirmed_not_executed: bool = False,
    ) -> None:
        """Operator-only: resolve an uncertain action; never blindly replay it."""
        if not actor or not evidence or ((result is not None) == confirmed_not_executed):
            raise ValueError(
                "Supply evidence and exactly one outcome: result or confirmed_not_executed"
            )
        if result is not None:
            value = json.loads(result)
            if not isinstance(value, dict) or type(value.get("ok")) is not bool:
                raise ValueError("Result must be a serialized tool result envelope")

        def op(conn: sqlite3.Connection) -> None:
            row = conn.execute("SELECT owner FROM executions WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0] is not None:
                raise ConcurrentUpdateError("Stop/recover the execution before reconciliation")
            action = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND call_id=?", (run_id, call_id)
            ).fetchone()
            if action is None or action[0] != "started":
                raise ValueError("Action is not awaiting reconciliation")
            if confirmed_not_executed:
                conn.execute("DELETE FROM actions WHERE run_id=? AND call_id=?", (run_id, call_id))
            else:
                conn.execute(
                    "UPDATE actions SET status='completed',result=? WHERE run_id=? AND call_id=?",
                    (result, run_id, call_id),
                )
            conn.execute(
                "INSERT INTO reconciliations(run_id,call_id,actor,evidence,occurred_at) "
                "VALUES (?,?,?,?,?)",
                (run_id, call_id, actor, evidence, datetime.now(UTC).isoformat()),
            )

        await self._call(op)

    async def unresolved_action(self, run_id: str, owner: str) -> str | None:
        def op(conn: sqlite3.Connection) -> str | None:
            self._owner(conn, run_id, owner)
            row = conn.execute(
                "SELECT call_id FROM actions WHERE run_id=? AND status='started' LIMIT 1", (run_id,)
            ).fetchone()
            return row[0] if row else None

        return await self._call(op)

    async def budget(
        self, run_id: str, owner: str, values: Mapping[str, int] | None = None
    ) -> dict[str, int]:
        def op(conn: sqlite3.Connection) -> dict[str, int]:
            self._owner(conn, run_id, owner)
            row = conn.execute("SELECT budget FROM executions WHERE run_id=?", (run_id,)).fetchone()
            current = cast(dict[str, int], json.loads(row[0]))
            if values is not None:
                # Monotonic floor prevents a crash from refunding in-flight reservations.
                current = {key: max(value, current.get(key, 0)) for key, value in values.items()}
                conn.execute(
                    "UPDATE executions SET budget=? WHERE run_id=?", (_json(current), run_id)
                )
            return current

        return await self._call(op)


class SQLiteApprovalStore:
    """Trusted-application approval port. Enforce reviewer ACLs before decide()."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    @staticmethod
    def _decode(value: str) -> Any:
        from ..governance.approval import ApprovalRequest, ApprovalStatus

        data = json.loads(value)
        data["status"] = ApprovalStatus(data["status"])
        return ApprovalRequest(**data)

    async def create(self, request: Any) -> None:
        await self.store._call(
            lambda conn: conn.execute(
                "INSERT INTO approvals VALUES (?,?,?,?)",
                (request.request_id, request.run_id, request.proposal_hash, _json(asdict(request))),
            )
        )

    async def get(self, request_id: str) -> Any:
        def op(conn: sqlite3.Connection) -> Any:
            row = conn.execute("SELECT data FROM approvals WHERE id=?", (request_id,)).fetchone()
            return self._decode(row[0]) if row else None

        return await self.store._call(op)

    async def find(self, run_id: str, proposal_hash: str) -> Any:
        def op(conn: sqlite3.Connection) -> Any:
            row = conn.execute(
                "SELECT data FROM approvals WHERE run_id=? AND digest=? "
                "ORDER BY rowid DESC LIMIT 1",
                (run_id, proposal_hash),
            ).fetchone()
            return self._decode(row[0]) if row else None

        return await self.store._call(op)

    async def _transition(self, request_id: str, target: Any, actor: str | None) -> Any:
        from ..governance.approval import ApprovalStatus

        def op(conn: sqlite3.Connection) -> Any:
            row = conn.execute("SELECT data FROM approvals WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise KeyError(request_id)
            current = self._decode(row[0])
            expected = (
                ApprovalStatus.APPROVED
                if target == ApprovalStatus.CONSUMED
                else ApprovalStatus.PENDING
            )
            if current.status != expected:
                raise ConcurrentUpdateError("Approval is no longer in its expected state")
            if current.expires_at and datetime.fromisoformat(current.expires_at) <= datetime.now(
                UTC
            ):
                raise ValueError("Approval has expired")
            updated = replace(
                current,
                status=target,
                decided_by=actor or current.decided_by,
                decided_at=datetime.now(UTC).isoformat(),
            )
            conn.execute(
                "UPDATE approvals SET data=? WHERE id=?", (_json(asdict(updated)), request_id)
            )
            return updated

        return await self.store._call(op)

    async def decide(self, request_id: str, status: Any, subject: str) -> Any:
        from ..governance.approval import ApprovalStatus

        if not subject or status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("A reviewer and approve/reject decision are required")
        return await self._transition(request_id, status, subject)

    async def consume(self, request_id: str) -> Any:
        from ..governance.approval import ApprovalStatus

        return await self._transition(request_id, ApprovalStatus.CONSUMED, None)
