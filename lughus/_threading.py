"""Small asyncio/thread bridge used for blocking framework work."""

from __future__ import annotations

import atexit
import asyncio
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import Any

DEFAULT_THREAD_WORKERS = 32

_process_executor: ThreadPoolExecutor | None = None
_process_executor_lock = threading.Lock()

_SYNC_SEMAPHORES: dict[tuple[weakref.ref[asyncio.AbstractEventLoop], int], asyncio.Semaphore] = {}
_SYNC_SEMAPHORES_LOCK = threading.Lock()


def _get_sync_semaphore(loop: asyncio.AbstractEventLoop, limit: int) -> asyncio.Semaphore:
    with _SYNC_SEMAPHORES_LOCK:
        # Clean up dead loops to prevent memory leaks
        dead_keys = [k for k in _SYNC_SEMAPHORES if k[0]() is None]
        for dk in dead_keys:
            _SYNC_SEMAPHORES.pop(dk, None)

        loop_ref = weakref.ref(loop)
        key = (loop_ref, limit)
        sem = _SYNC_SEMAPHORES.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            _SYNC_SEMAPHORES[key] = sem
        return sem


def _executor(max_workers: int | None) -> ThreadPoolExecutor:
    global _process_executor
    workers = max_workers if max_workers and max_workers > 0 else DEFAULT_THREAD_WORKERS
    with _process_executor_lock:
        if _process_executor is None:
            _process_executor = ThreadPoolExecutor(
                max_workers=max(workers, DEFAULT_THREAD_WORKERS),
                thread_name_prefix="lughus-worker",
            )
        return _process_executor


def _shutdown_executors() -> None:
    global _process_executor
    with _process_executor_lock:
        if _process_executor is not None:
            _process_executor.shutdown(wait=False)
            _process_executor = None


atexit.register(_shutdown_executors)


async def run_sync_in_thread(
    call: Callable[[], Any],
    *,
    max_workers: int | None = None,
) -> Any:
    """Run ``call`` on a bounded process-wide executor."""
    loop = asyncio.get_running_loop()
    executor = _executor(max_workers)
    if max_workers and max_workers > 0:
        sem = _get_sync_semaphore(loop, max_workers)
        async with sem:
            return await loop.run_in_executor(executor, call)
    return await loop.run_in_executor(executor, call)
