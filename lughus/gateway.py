"""Base A2A gateway — message extraction and generic artifact handling."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import re
from typing import TYPE_CHECKING, Any, AsyncIterator

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    FileWithBytes,
    FilePart,
    Part,
    TaskState,
    TextPart,
)
from opentelemetry.trace import StatusCode

from ._threading import run_sync_in_thread
from .config import BaseSettings
from .events import Artifact, CompletionEvent, ProgressEvent
from .telemetry import tracer

if TYPE_CHECKING:
    from .llm import LLM

_logger = logging.getLogger(__name__)


def _safe_filename(name: str | None) -> str:
    """Return a path-free filename suitable for handing to agent code."""
    value = (name or "file").replace("\\", "/")
    filename = os.path.basename(value).replace("\x00", "").strip()
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    if filename in {"", ".", ".."}:
        return "file"
    return filename


def _validate_objective(objective: str, settings: BaseSettings) -> None:
    limit = getattr(settings, "max_objective_chars", 100_000)
    if limit > 0 and len(objective) > limit:
        raise ValueError(f"Objective exceeds max length of {limit} characters")


def _validate_artifacts(artifacts: list[Artifact], settings: BaseSettings) -> None:
    max_artifacts = getattr(settings, "max_artifacts", 10)
    if max_artifacts > 0 and len(artifacts) > max_artifacts:
        raise ValueError(f"Too many artifacts: max {max_artifacts}")

    total_bytes = sum(len(artifact.data) for artifact in artifacts)
    max_total_artifact_bytes = getattr(settings, "max_total_artifact_bytes", 100 * 1024 * 1024)
    if max_total_artifact_bytes > 0 and total_bytes > max_total_artifact_bytes:
        raise ValueError(f"Artifacts exceed total max size {max_total_artifact_bytes} bytes")

    max_artifact_bytes = getattr(settings, "max_artifact_bytes", 50 * 1024 * 1024)
    if max_artifact_bytes <= 0:
        return
    for artifact in artifacts:
        if len(artifact.data) > max_artifact_bytes:
            raise ValueError(
                f"Artifact '{artifact.name}' exceeds max size {max_artifact_bytes} bytes"
            )


class BaseGateway(AgentExecutor):
    """Generic A2A gateway. Subclass and implement ``handle()``."""

    def __init__(self, llm: LLM, settings: BaseSettings):
        self.llm = llm
        self.settings = settings
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        updater = TaskUpdater(
            event_queue,
            context.task_id or "",
            context.context_id or "",
        )
        task_id = context.task_id or ""
        current_task = asyncio.current_task()
        if task_id and current_task is not None:
            self._running_tasks[task_id] = current_task
        await updater.start_work()

        with tracer.start_as_current_span("a2a.request") as span:
            try:
                objective, files = await self._extract_async(context)
                span.set_attribute("lughus.objective_len", len(objective))
                span.set_attribute("lughus.file_count", len(files))

                timeout_ctx = (
                    asyncio.timeout(self.settings.agent_timeout)
                    if self.settings.agent_timeout > 0
                    else contextlib.nullcontext()
                )

                completed = False
                async with timeout_ctx:
                    async for event in self.handle(objective, files):
                        if isinstance(event, ProgressEvent):
                            if completed:
                                _logger.warning(
                                    "Ignoring ProgressEvent after completion for task '%s'",
                                    context.task_id or "",
                                )
                                continue
                            msg = updater.new_agent_message(
                                parts=[Part(root=TextPart(text=event.text))],
                            )
                            await updater.update_status(TaskState.working, message=msg)

                        elif isinstance(event, CompletionEvent):
                            if completed:
                                _logger.warning(
                                    "Ignoring additional CompletionEvent for task '%s'",
                                    context.task_id or "",
                                )
                                continue
                            _validate_artifacts(event.artifacts, self.settings)
                            span.set_attribute("lughus.artifact_count", len(event.artifacts))
                            span.set_attribute(
                                "lughus.artifact_bytes",
                                sum(len(artifact.data) for artifact in event.artifacts),
                            )
                            for artifact in event.artifacts:
                                encoded = base64.b64encode(artifact.data).decode("ascii")
                                await updater.add_artifact(
                                    parts=[
                                        Part(
                                            root=FilePart(
                                                file=FileWithBytes(
                                                    bytes=encoded,
                                                    mime_type=artifact.mime_type,
                                                    name=artifact.name,
                                                ),
                                            )
                                        )
                                    ],
                                    name=artifact.name,
                                )

                            msg = updater.new_agent_message(
                                parts=[Part(root=TextPart(text=event.text))],
                            )
                            await updater.complete(message=msg)
                            completed = True

                if not completed:
                    raise RuntimeError("Agent handler finished without CompletionEvent")

                span.set_attribute("lughus.status", "completed")
                span.set_status(StatusCode.OK)

            except TimeoutError as exc:
                span.set_status(StatusCode.ERROR, "agent timeout exceeded")
                span.record_exception(exc)
                span.set_attribute("lughus.status", "timeout")
                msg = updater.new_agent_message(
                    parts=[
                        Part(
                            root=TextPart(
                                text=f"Error: Agent execution timed out after {self.settings.agent_timeout}s"
                            )
                        )
                    ],
                )
                await updater.failed(message=msg)

            except asyncio.CancelledError:
                span.set_status(StatusCode.ERROR, "agent cancelled")
                span.set_attribute("lughus.status", "cancelled")

            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                span.set_attribute("lughus.status", "failed")
                msg = updater.new_agent_message(
                    parts=[Part(root=TextPart(text=f"Error: {exc}"))],
                )
                await updater.failed(message=msg)
            finally:
                if task_id and self._running_tasks.get(task_id) is current_task:
                    self._running_tasks.pop(task_id, None)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        updater = TaskUpdater(
            event_queue,
            context.task_id or "",
            context.context_id or "",
        )
        await updater.cancel()
        task = self._running_tasks.get(context.task_id or "")
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def shutdown(self) -> None:
        """Cancel all currently running A2A tasks for graceful shutdown."""
        tasks = list(self._running_tasks.values())
        if not tasks:
            return
        _logger.info("Cancelling %d running tasks for graceful shutdown...", len(tasks))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def handle(
        self,
        objective: str,
        files: list[tuple[bytes, str, str]],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        """Implement in your agent. Yield ProgressEvent / CompletionEvent."""
        raise NotImplementedError
        if False:
            yield ProgressEvent("")

    # -- A2A message extraction -----------------------------------

    def _parse_message_parts(
        self,
        context: RequestContext,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Parse A2A message parts and return (text_parts, file_tasks) without decoding base64."""
        text_parts: list[str] = []
        file_tasks: list[dict[str, Any]] = []
        pending_name: str | None = None

        message = context.message
        if message is None:
            return [], []

        for part in message.parts:
            p = part.root

            if isinstance(p, TextPart):
                if p.text.startswith("__ORIGINAL_FILENAME__:"):
                    pending_name = p.text[len("__ORIGINAL_FILENAME__:") :]
                else:
                    text_parts.append(p.text)
                continue

            if isinstance(p, FilePart):
                fw = p.file
                if isinstance(fw, FileWithBytes):
                    if len(file_tasks) >= self.settings.max_files:
                        _logger.warning(
                            "Skipping file '%s': max file count %d reached",
                            fw.name or "(unnamed)",
                            self.settings.max_files,
                        )
                        continue

                    max_encoded_bytes = ((self.settings.max_file_bytes + 2) // 3) * 4
                    if len(fw.bytes) > max_encoded_bytes:
                        _logger.warning(
                            "Skipping file '%s': encoded size %d bytes exceeds max decoded limit %d bytes",
                            fw.name or "(unnamed)",
                            len(fw.bytes),
                            self.settings.max_file_bytes,
                        )
                        continue

                    name = _safe_filename(pending_name or fw.name)
                    pending_name = None
                    file_tasks.append(
                        {
                            "bytes": fw.bytes,
                            "mime": fw.mime_type or "application/octet-stream",
                            "name": name,
                        }
                    )
        return text_parts, file_tasks

    def _process_decoded_file(
        self,
        raw: bytes,
        task: dict[str, Any],
        total_file_bytes: int,
    ) -> tuple[bytes, str, str] | None:
        """Validate size limits on a decoded file and return the file tuple or None."""
        if len(raw) > self.settings.max_file_bytes:
            _logger.warning(
                "Skipping file '%s': size %d bytes exceeds limit %d bytes",
                task["name"],
                len(raw),
                self.settings.max_file_bytes,
            )
            return None

        if total_file_bytes + len(raw) > self.settings.max_request_bytes:
            _logger.warning(
                "Skipping file '%s': total decoded file bytes would exceed limit %d bytes",
                task["name"],
                self.settings.max_request_bytes,
            )
            return None

        return raw, task["mime"], task["name"]

    async def _extract_async(
        self,
        context: RequestContext,
    ) -> tuple[str, list[tuple[bytes, str, str]]]:
        """Parse an A2A message without blocking the event loop on large file decode."""
        text_parts, file_tasks = self._parse_message_parts(context)
        files: list[tuple[bytes, str, str]] = []
        total_file_bytes = 0

        for task in file_tasks:
            try:
                raw = await run_sync_in_thread(
                    lambda: base64.b64decode(task["bytes"], validate=True),
                    max_workers=self.settings.max_sync_thread_workers,
                )
            except Exception as exc:
                _logger.warning(
                    "Skipping file '%s': base64 decode failed — %s",
                    task["name"],
                    exc,
                )
                continue

            res = self._process_decoded_file(raw, task, total_file_bytes)
            if res is not None:
                files.append(res)
                total_file_bytes += len(res[0])

        objective = "\n".join(text_parts)
        _validate_objective(objective, self.settings)
        return objective, files

    def _extract(
        self,
        context: RequestContext,
    ) -> tuple[str, list[tuple[bytes, str, str]]]:
        """Parse an A2A message into (objective_text, [(data, mime, name), ...])."""
        text_parts, file_tasks = self._parse_message_parts(context)
        files: list[tuple[bytes, str, str]] = []
        total_file_bytes = 0

        for task in file_tasks:
            try:
                raw = base64.b64decode(task["bytes"], validate=True)
            except Exception as exc:
                _logger.warning(
                    "Skipping file '%s': base64 decode failed — %s",
                    task["name"],
                    exc,
                )
                continue

            res = self._process_decoded_file(raw, task, total_file_bytes)
            if res is not None:
                files.append(res)
                total_file_bytes += len(res[0])

        objective = "\n".join(text_parts)
        _validate_objective(objective, self.settings)
        return objective, files
