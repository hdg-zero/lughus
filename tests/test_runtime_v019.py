"""Runtime invariants runnable with unittest, without provider dependencies."""

import asyncio
import contextvars
import unittest

from lughus.infra.runtime import ExecutionRuntime, RuntimeConfig


class Runtime019Tests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_context_propagates(self) -> None:
        marker = contextvars.ContextVar("marker", default="unset")
        marker.set("request")
        async with ExecutionRuntime() as runtime:
            self.assertEqual(await runtime.run_sync(marker.get), "request")

    async def test_exclusive_excludes_parallel(self) -> None:
        runtime = ExecutionRuntime(RuntimeConfig(max_sync_workers=1))
        entered = asyncio.Event()
        release = asyncio.Event()
        seen = []

        async def exclusive() -> None:
            async with runtime.execution_slot(exclusive=True):
                entered.set()
                await release.wait()
                seen.append("exclusive")

        async def parallel() -> None:
            await entered.wait()
            async with runtime.execution_slot():
                seen.append("parallel")

        one = asyncio.create_task(exclusive())
        two = asyncio.create_task(parallel())
        async with asyncio.timeout(5):
            await entered.wait()
        await asyncio.sleep(0)
        self.assertEqual(seen, [])
        release.set()
        async with asyncio.timeout(5):
            await asyncio.gather(one, two)
        self.assertEqual(seen, ["exclusive", "parallel"])
        await runtime.close()

    async def test_cancelled_writer_does_not_block_readers(self) -> None:
        async with ExecutionRuntime() as runtime:
            async with runtime.execution_slot():

                async def writer() -> None:
                    async with runtime.execution_slot(exclusive=True):
                        pass

                task = asyncio.create_task(writer())
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            async with asyncio.timeout(1):
                async with runtime.execution_slot():
                    pass
