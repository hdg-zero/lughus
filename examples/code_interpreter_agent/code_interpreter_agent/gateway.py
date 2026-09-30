"""A2A Gateway bridging remote JSON-RPC / SSE requests to the Code Interpreter workspace."""

from __future__ import annotations

from collections.abc import AsyncIterator

from lughus import LLM, BaseGateway, CompletionEvent, ProgressEvent

from .config import Settings
from .workspace import Workspace

__all__ = ["CodeInterpreterGateway"]


class CodeInterpreterGateway(BaseGateway):
    """Bridge incoming A2A messages to the governed Code Interpreter Workspace."""

    def __init__(self, llm: LLM, settings: Settings) -> None:
        super().__init__(llm=llm, settings=settings)
        self._settings = settings

    async def handle(
        self,
        objective: str,
        files: list[tuple[bytes, str, str]],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        """Execute Data Science calculations in the sandbox and stream progress and artifacts."""
        tool_config = self.create_tool_config(
            tool_timeout=self._settings.tool_timeout,
            max_context_tokens=self._settings.max_context_tokens,
        )
        workspace = Workspace(
            objective=objective,
            files=files,
            llm=self.llm,
            settings=self._settings,
            tool_config=tool_config,
        )
        async for event in workspace.run():
            yield event
