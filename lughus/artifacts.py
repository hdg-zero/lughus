"""Artifact projection -- store large tool outputs and replace them with references.

When artifact projection is enabled, tool outputs exceeding a configurable
threshold are stored in an in-memory ``ArtifactStore`` and replaced in the message
history by a short reference containing a summary.  The model can retrieve the full
content via the ``fetch_artifact`` built-in tool.

The store is per-run (in-memory) and not persistent.
"""

from __future__ import annotations

import json
import uuid
from typing import Any


class ArtifactStore:
    """In-memory store mapping artifact_id -> content string.

    Each agent run should create its own ``ArtifactStore`` instance;
    the store is not designed for persistence or cross-run sharing.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def store_artifact(self, content: str) -> str:
        """Store *content* and return a unique ``artifact_id`` (UUID)."""
        artifact_id = uuid.uuid4().hex
        self._store[artifact_id] = content
        return artifact_id

    def fetch_artifact(
        self,
        artifact_id: str,
        offset: int = 0,
        length: int | None = None,
    ) -> str:
        """Retrieve full or partial content for *artifact_id*.

        Parameters
        ----------
        artifact_id:
            The identifier returned by :meth:`store_artifact`.
        offset:
            Character offset to start reading from (default ``0``).
        length:
            Maximum number of characters to return.  ``None`` means
            "everything from *offset* to the end".

        Raises
        ------
        KeyError
            If *artifact_id* is not found in the store.
        """
        content = self._store[artifact_id]
        if length is None:
            return content[offset:]
        return content[offset : offset + length]

    def __contains__(self, artifact_id: str) -> bool:
        return artifact_id in self._store

    def __len__(self) -> int:
        return len(self._store)


def _summarize(content: str) -> dict[str, Any]:
    """Produce a compact summary of *content* for the projection reference.

    Returns a dict with ``type``, ``size``, and ``preview`` keys.  For JSON
    content the top-level keys are included when the value is an object.
    """
    size = len(content)
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {
            "type": "text",
            "size": size,
            "preview": content[:200] + ("..." if size > 200 else ""),
        }

    summary: dict[str, Any] = {"size": size}
    if isinstance(parsed, dict):
        summary["type"] = "json_object"
        summary["keys"] = list(parsed.keys())[:20]
    elif isinstance(parsed, list):
        summary["type"] = "json_array"
        summary["length"] = len(parsed)
    else:
        summary["type"] = "json_scalar"

    preview = content[:200] + ("..." if size > 200 else "")
    summary["preview"] = preview
    return summary
