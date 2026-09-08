"""Real SQLite transactions and crash boundaries, stdlib-only."""

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lughus.core.domain import RunEvent, RunStatus
from lughus.governance.approval import ApprovalRequest, ApprovalStatus
from lughus.governance.budget import BudgetAmount, BudgetExceeded, BudgetLimit
from lughus.persistence.coordinator import RunCoordinator
from lughus.persistence.execution import ExecutionJournal, JournalBudget, OutcomeUnknown
from lughus.persistence.sqlite import SQLiteApprovalStore, SQLiteStore
from lughus.persistence.store import ConcurrentUpdateError


class SQLiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "runs.db")
        self.store = SQLiteStore(self.path)
        self.coordinator = RunCoordinator(self.store)
        self.run = await self.coordinator.start("test", tenant_id="t", principal_id="u")
        self.run = await self.coordinator.transition(self.run, RunStatus.RUNNING, "run.started")

    async def asyncTearDown(self) -> None:
        self.directory.cleanup()

    async def test_lifecycle_persists_across_instances(self) -> None:
        store = SQLiteStore(self.path)
        self.assertEqual((await store.get(self.run.run_id)).status, RunStatus.RUNNING)
        self.assertEqual(len(await store.read(self.run.run_id)), 2)

    async def test_event_failure_rolls_back_status(self) -> None:
        checkpoint = await self.store.latest(self.run.run_id)
        with self.assertRaises(ConcurrentUpdateError):
            await self.store.commit_transition(
                run_id=self.run.run_id,
                expected_version=self.run.version,
                status=RunStatus.COMPLETED,
                event=RunEvent("duplicate", self.run.run_id, checkpoint.sequence),
                checkpoint=checkpoint,
            )
        current = await self.store.get(self.run.run_id)
        self.assertEqual(current.version, self.run.version)
        self.assertEqual(current.status, RunStatus.RUNNING)

    async def test_exclusive_execution_owner(self) -> None:
        await self.store.open_execution(self.run.run_id, "one", {"loop": {}})
        with self.assertRaises(ConcurrentUpdateError):
            await SQLiteStore(self.path).open_execution(self.run.run_id, "two", None)
        await self.store.release_execution(self.run.run_id, "one")
        self.assertEqual(
            await self.store.open_execution(self.run.run_id, "two", None), {"loop": {}}
        )

    async def test_completed_receipt_is_reusable_not_reexecuted(self) -> None:
        await self.store.open_execution(self.run.run_id, "one", {})
        journal = ExecutionJournal(self.store, self.run.run_id, "one")
        await journal.start("1:t1", "pay", "1", {"amount": 4})
        await journal.complete("1:t1", '{"ok":true,"result":"paid"}')
        self.assertIn("paid", await journal.lookup("1:t1", "pay", "1", {"amount": 4}))
        self.assertIsNone(await journal.lookup("2:t1", "pay", "1", {"amount": 4}))
        with self.assertRaises(ValueError):
            await journal.lookup("1:t1", "pay", "2", {"amount": 4})

    async def test_real_process_crash_requires_reconciliation(self) -> None:
        script = """import asyncio, os, sys
from lughus.persistence.sqlite import SQLiteStore
from lughus.persistence.execution import ExecutionJournal
async def main():
 s=SQLiteStore(sys.argv[1]); r=sys.argv[2]
 await s.open_execution(r, 'crashed-worker', {'loop': {}})
 await ExecutionJournal(s,r,'crashed-worker').start('1:t1','pay','1',{'amount':4})
 os._exit(17)
asyncio.run(main())
"""
        result = await asyncio.to_thread(
            subprocess.run, [sys.executable, "-c", script, self.path, self.run.run_id], check=False
        )
        self.assertEqual(result.returncode, 17)
        await self.store.recover_execution(
            self.run.run_id,
            "crashed-worker",
            actor="operator",
            evidence="Child process exited with code 17",
        )
        await self.store.open_execution(self.run.run_id, "new", None)
        journal = ExecutionJournal(self.store, self.run.run_id, "new")
        with self.assertRaises(OutcomeUnknown):
            await journal.lookup("1:t1", "pay", "1", {"amount": 4})
        await self.store.release_execution(self.run.run_id, "new")
        await self.store.reconcile_action(
            self.run.run_id,
            "1:t1",
            actor="operator",
            evidence="External system confirms payment",
            result='{"ok":true,"result":"paid"}',
        )
        await self.store.open_execution(self.run.run_id, "next", None)
        self.assertIn(
            "paid",
            await ExecutionJournal(self.store, self.run.run_id, "next").lookup(
                "1:t1", "pay", "1", {"amount": 4}
            ),
        )

    async def test_budget_reservation_survives_restart(self) -> None:
        await self.store.open_execution(self.run.run_id, "one", {})
        journal = ExecutionJournal(self.store, self.run.run_id, "one")
        ledger = JournalBudget(BudgetLimit(model_calls=1), journal, {})
        await ledger.reserve(BudgetAmount(model_calls=1))
        persisted = await self.store.budget(self.run.run_id, "one")
        restored = JournalBudget(BudgetLimit(model_calls=1), journal, persisted)
        with self.assertRaises(BudgetExceeded):
            await restored.reserve(BudgetAmount(model_calls=1))

    async def test_durable_approval_consumed_once(self) -> None:
        approvals = SQLiteApprovalStore(self.store)
        request = ApprovalRequest(self.run.run_id, "pay", "digest", "high")
        await approvals.create(request)
        await approvals.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")
        other = SQLiteApprovalStore(SQLiteStore(self.path))
        await other.consume(request.request_id)
        with self.assertRaises(ConcurrentUpdateError):
            await approvals.consume(request.request_id)

    async def test_approval_store_queries_and_validations(self) -> None:
        approvals = SQLiteApprovalStore(self.store)
        request = ApprovalRequest(self.run.run_id, "pay", "digest123", "high")
        await approvals.create(request)
        fetched = await approvals.get(request.request_id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.request_id, request.request_id)
        self.assertIsNone(await approvals.get("unknown_id"))

        found = await approvals.find(self.run.run_id, "digest123")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.request_id, request.request_id)
        self.assertIsNone(await approvals.find(self.run.run_id, "other_digest"))

        with self.assertRaises(ValueError):
            await approvals.decide(request.request_id, ApprovalStatus.APPROVED, "")
        with self.assertRaises(ValueError):
            await approvals.decide(request.request_id, ApprovalStatus.PENDING, "reviewer")
        with self.assertRaises(KeyError):
            await approvals.consume("nonexistent")
        with self.assertRaises(ConcurrentUpdateError):
            await approvals.consume(request.request_id)

    async def test_expired_approval_cannot_be_decided(self) -> None:
        approvals = SQLiteApprovalStore(self.store)
        request = ApprovalRequest(
            self.run.run_id, "pay", "exp_digest", "high", expires_at="2020-01-01T00:00:00+00:00"
        )
        await approvals.create(request)
        with self.assertRaises(ValueError):
            await approvals.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")

    async def test_unresolved_action_and_confirmed_not_executed(self) -> None:
        await self.store.open_execution(self.run.run_id, "worker", {})
        self.assertIsNone(await self.store.unresolved_action(self.run.run_id, "worker"))

        journal = ExecutionJournal(self.store, self.run.run_id, "worker")
        await journal.start("1:action", "tool_x", "1", {"arg": "val"})
        self.assertEqual(await self.store.unresolved_action(self.run.run_id, "worker"), "1:action")

        await self.store.release_execution(self.run.run_id, "worker")
        with self.assertRaises(ValueError):
            await self.store.reconcile_action(self.run.run_id, "1:action", actor="", evidence="ev")
        with self.assertRaises(ValueError):
            await self.store.reconcile_action(
                self.run.run_id,
                "1:action",
                actor="op",
                evidence="ev",
                result='{"ok":true}',
                confirmed_not_executed=True,
            )
        with self.assertRaises(ValueError):
            await self.store.reconcile_action(
                self.run.run_id,
                "nonexistent",
                actor="op",
                evidence="ev",
                confirmed_not_executed=True,
            )

        await self.store.reconcile_action(
            self.run.run_id,
            "1:action",
            actor="operator",
            evidence="Confirmed cancelled remotely",
            confirmed_not_executed=True,
        )

    async def test_execution_snapshot_limits_and_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            await self.store.open_execution("unknown_run", "worker", None)
        with self.assertRaises(ValueError):
            await self.store.open_execution(self.run.run_id, "worker", {"big": "x" * 5_000_000})
        with self.assertRaises(ValueError):
            await self.store.snapshot_execution(self.run.run_id, "worker", {"big": "x" * 5_000_000})

        import sqlite3

        db_file = str(Path(self.directory.name) / "bad_schema.db")
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA user_version=99")
        conn.close()
        with self.assertRaises(ValueError):
            SQLiteStore(db_file)
