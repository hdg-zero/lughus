"""Small asyncio/thread bridge used for blocking framework work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


async def run_sync_in_thread(
    call: Callable[[], Any],
    *,
    executor: ThreadPoolExecutor | None = None,
    max_workers: int | None = None,
) -> Any:
    """Run ``call`` on the provided executor or worker thread."""
    if executor is not None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, call)
    return await asyncio.to_thread(call)
