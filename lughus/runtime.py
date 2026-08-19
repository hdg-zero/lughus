"""Explicit ownership of process-local execution resources."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any

from .errors import ToolTimeoutError


@dataclass(slots=True)
class _LockEntry:
    """A resource lock plus the number of tasks currently interested in it.

    ``_resource_locks`` used ``setdefault`` and never removed an
    entry, so the dict grew with every distinct resource key ever seen -- and keys
    are derived from tool arguments (``f"{name}:{tool.resource_key(args)}"``),
    i.e. potentially from model-controlled data. Reference counting bounds the dict
    by *actual concurrency* instead of by history, which is both simpler and more
    correct than evicting on a heuristic: an entry is dropped only once the last
    interested task has released it, so a held lock can never be removed from under
    its holder.
    """

    lock: asyncio.Lock
    waiters: int = 0


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    max_global_tools: int = 64
    max_sync_workers: int = 32
    queue_timeout: float | None = None

    def __post_init__(self) -> None:
        if self.max_global_tools <= 0 or self.max_sync_workers <= 0:
            raise ValueError("Runtime capacities must be positive")
        if self.queue_timeout is not None and self.queue_timeout < 0:
            raise ValueError("queue_timeout cannot be negative")


class ExecutionRuntime:
    """Own the bulkhead and thread pool shared deliberately by agent runs.

    A runtime is bound to the first event loop that uses it. Applications requiring more
    than one loop create one runtime per loop. ``close`` is explicit and idempotent.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.max_sync_workers,
            thread_name_prefix="lughus-tool",
        )
        self._semaphore = asyncio.Semaphore(self.config.max_global_tools)
        self._resource_locks: dict[str, _LockEntry] = {}
        self._global_exclusive_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    def _bind(self) -> asyncio.AbstractEventLoop:
        if self._closed:
            raise RuntimeError("ExecutionRuntime is closed")
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("ExecutionRuntime cannot be shared across event loops")
        return loop

    @property
    def global_exclusive_lock(self) -> asyncio.Lock:
        """Return the single process-wide lock used by GLOBAL_EXCLUSIVE tools."""
        return self._global_exclusive_lock

    @asynccontextmanager
    async def tool_slot(self, timeout: float | None = None) -> AsyncIterator[None]:
        self._bind()
        wait = self.config.queue_timeout if timeout is None else timeout
        try:
            if wait is None:
                await self._semaphore.acquire()
            elif wait == 0:
                if self._semaphore.locked():
                    raise ToolTimeoutError("No global tool slot is available")
                await self._semaphore.acquire()
            else:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=wait)
        except TimeoutError as exc:
            raise ToolTimeoutError("Timed out waiting for a global tool slot") from exc
        try:
            yield
        finally:
            self._semaphore.release()

    async def run_sync(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        loop = self._bind()
        context_call = partial(fn, *args, **kwargs)
        return await loop.run_in_executor(self._executor, context_call)

    @asynccontextmanager
    async def resource_slot(self, key: str) -> AsyncIterator[None]:
        self._bind()
        entry = self._resource_locks.get(key)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            self._resource_locks[key] = entry
        entry.waiters += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.waiters -= 1
            if entry.waiters == 0:
                # Nobody is interested in this resource any more, so the entry
                # cannot be serving anyone: dropping it is safe by construction.
                self._resource_locks.pop(key, None)

    async def close(self, *, wait: bool = True) -> None:
        """Shut the thread pool down. Idempotent.

        ``wait`` used to be ignored -- ``shutdown(wait=False)`` ran
        whatever the caller asked, so ``await runtime.close(wait=True)`` could
        return while synchronous tools were still executing side effects.

        ``shutdown(wait=True)`` blocks, so it is offloaded to a thread: running it
        on the event loop would stall every other task in the process.
        """
        if self._closed:
            return
        self._closed = True
        if wait:
            await asyncio.to_thread(self._executor.shutdown, True)
        else:
            self._executor.shutdown(wait=False, cancel_futures=True)

    async def __aenter__(self) -> ExecutionRuntime:
        self._bind()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
