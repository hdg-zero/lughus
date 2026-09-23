"""A2A Gateway bridging remote JSON-RPC / SSE requests to the Data Ingestion workspace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from lughus import LLM, BaseGateway, CompletionEvent, ProgressEvent

from .config import Settings
from .database import init_demo_database
from .workspace import Workspace

__all__ = ["DataIngestionGateway"]


class DataIngestionGateway(BaseGateway):
    """Bridge incoming A2A messages to the governed Data Ingestion Workspace."""

    def __init__(self, llm: LLM, settings: Settings) -> None:
        super().__init__(llm=llm, settings=settings)
        self._settings = settings
        # Ensure the local SQLite database exists on startup
        init_demo_database(self._settings.database_path)

    async def handle(
        self,
        objective: str,
        files: list[Any],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        """Process an analytical data extraction objective."""
        tool_config = self.create_tool_config()
        workspace = Workspace(
            objective=objective,
            files=files,
            llm=self.llm,
            tool_config=tool_config,
        )
        async for event in workspace.run():
            yield event
