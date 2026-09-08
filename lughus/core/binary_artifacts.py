"""Application-owned filesystem artifact persistence; no model-chosen paths."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .events import Artifact


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    artifact_id: str
    name: str
    mime_type: str
    size: int
    sha256: str


class BinaryArtifactStore(Protocol):
    def put(self, artifact: Artifact) -> ArtifactReference: ...


class FileArtifactStore:
    """Persist files beneath a trusted, application-selected directory.

    Authorization, retention, total disk quota and download serving belong to the
    embedding application. IDs are random and filenames are metadata only.
    """

    def __init__(self, directory: str | Path, *, max_file_bytes: int = 10_000_000) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_file_bytes = max_file_bytes

    def put(self, artifact: Artifact) -> ArtifactReference:
        if len(artifact.data) > self.max_file_bytes:
            raise ValueError("Artifact exceeds configured size limit")
        artifact_id = uuid4().hex
        path = self.directory / artifact_id
        # Directory must be application-owned, not writable by untrusted code.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(artifact.data)
                output.flush()
                os.fsync(output.fileno())
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return ArtifactReference(
            artifact_id,
            Path(artifact.name).name,
            artifact.mime_type,
            len(artifact.data),
            hashlib.sha256(artifact.data).hexdigest(),
        )
