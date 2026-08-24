"""Small asyncio/thread bridge used for blocking framework work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


async def run_sync_in_thread(
    call: Callable[[], Any],
    *,
    executor: ThreadPoolExecutor,
    max_workers: int | None = None,
) -> Any:
    """Run ``call`` on the provided executor with optional concurrency bounding."""
    loop = asyncio.get_running_loop()
    if max_workers and max_workers > 0:
        sem = asyncio.Semaphore(max_workers)
        async with sem:
            return await loop.run_in_executor(executor, call)
    return await loop.run_in_executor(executor, call)
