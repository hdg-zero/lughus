"""Tests for BaseGateway._extract() — A2A message parsing (fixes B2, M2)."""

from __future__ import annotations

import base64
import logging
from unittest.mock import MagicMock

import pytest

from lughus import Artifact
from lughus.gateway import BaseGateway, _validate_artifacts
from lughus.config import BaseSettings


def _make_gateway(
    monkeypatch,
    max_file_bytes: int = 25 * 1024 * 1024,
    max_files: int = 10,
    max_request_bytes: int = 50 * 1024 * 1024,
    max_objective_chars: int = 100_000,
) -> BaseGateway:
    """Build a BaseGateway with a mock LLM and custom settings."""
    monkeypatch.setenv("AGENT_MODEL", "test/model")
    monkeypatch.setenv("MAX_FILE_BYTES", str(max_file_bytes))
    monkeypatch.setenv("MAX_FILES", str(max_files))
    monkeypatch.setenv("MAX_REQUEST_BYTES", str(max_request_bytes))
    monkeypatch.setenv("MAX_OBJECTIVE_CHARS", str(max_objective_chars))

    from lughus.llm import LLM
    from unittest.mock import MagicMock

    # We use a concrete subclass because BaseGateway.handle() is abstract
    class ConcreteGateway(BaseGateway):
        async def handle(self, objective, files):
            return
            yield  # make it an async generator

    settings = BaseSettings()
    llm = MagicMock(spec=LLM)
    llm.model = "test/model"
    return ConcreteGateway(llm=llm, settings=settings)


def _make_context(parts) -> MagicMock:
    """Build a mock A2A RequestContext from a list of Part mocks."""
    message = MagicMock()
    message.parts = parts
    context = MagicMock()
    context.message = message
    return context


def _text_part(text: str) -> MagicMock:
    from a2a.types import TextPart

    part = MagicMock()
    part.root = MagicMock(spec=TextPart)
    part.root.text = text
    return part


def _file_part(data: bytes, mime: str = "application/pdf", name: str = "file.pdf") -> MagicMock:
    from a2a.types import FilePart, FileWithBytes

    fw = MagicMock(spec=FileWithBytes)
    fw.bytes = base64.b64encode(data).decode()
    fw.mime_type = mime
    fw.name = name

    fp = MagicMock(spec=FilePart)
    fp.file = fw

    part = MagicMock()
    part.root = fp
    return part


def _invalid_file_part(name: str = "bad.bin") -> MagicMock:
    from a2a.types import FilePart, FileWithBytes

    fw = MagicMock(spec=FileWithBytes)
    fw.bytes = "!!!NOT_VALID_BASE64!!!"
    fw.mime_type = "application/octet-stream"
    fw.name = name

    fp = MagicMock(spec=FilePart)
    fp.file = fw

    part = MagicMock()
    part.root = fp
    return part


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_extract_text_only(monkeypatch) -> None:
    """Simple text message → objective text, empty file list."""
    gw = _make_gateway(monkeypatch)
    ctx = _make_context([_text_part("Do the thing")])
    objective, files = gw._extract(ctx)
    assert objective == "Do the thing"
    assert files == []


def test_extract_multiple_text_parts(monkeypatch) -> None:
    """Multiple TextParts are joined with newlines."""
    gw = _make_gateway(monkeypatch)
    ctx = _make_context([_text_part("Part 1"), _text_part("Part 2")])
    objective, files = gw._extract(ctx)
    assert objective == "Part 1\nPart 2"


def test_extract_objective_length_limit(monkeypatch) -> None:
    gw = _make_gateway(monkeypatch, max_objective_chars=5)
    ctx = _make_context([_text_part("too long")])

    with pytest.raises(ValueError, match="Objective exceeds"):
        gw._extract(ctx)


def test_extract_file_part(monkeypatch) -> None:
    """Valid FilePart is decoded and included in files list."""
    gw = _make_gateway(monkeypatch)
    raw = b"PDF content here"
    ctx = _make_context([_text_part("Analyze this"), _file_part(raw, "application/pdf", "doc.pdf")])
    objective, files = gw._extract(ctx)
    assert objective == "Analyze this"
    assert len(files) == 1
    data, mime, name = files[0]
    assert data == raw
    assert mime == "application/pdf"
    assert name == "doc.pdf"


def test_extract_invalid_base64_skipped_with_warning(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B2 fix: corrupted base64 files are skipped with a WARNING log."""
    gw = _make_gateway(monkeypatch)
    ctx = _make_context([_text_part("Analyze"), _invalid_file_part("corrupt.bin")])

    with caplog.at_level(logging.WARNING, logger="lughus.gateway"):
        objective, files = gw._extract(ctx)

    assert objective == "Analyze"
    assert files == []
    assert "corrupt.bin" in caplog.text
    assert "base64" in caplog.text.lower()


def test_extract_file_exceeding_max_size_skipped_with_warning(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """M2 fix: files exceeding max_file_bytes are skipped with a WARNING log."""
    gw = _make_gateway(monkeypatch, max_file_bytes=10)  # tiny limit
    big_data = b"x" * 100  # 100 bytes > 10 bytes limit
    ctx = _make_context([_file_part(big_data, "application/octet-stream", "big.bin")])

    with caplog.at_level(logging.WARNING, logger="lughus.gateway"):
        objective, files = gw._extract(ctx)

    assert files == []
    assert "big.bin" in caplog.text
    assert "exceeds" in caplog.text.lower()


def test_extract_file_exceeding_encoded_max_size_skipped_before_decode(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Very large encoded payloads are rejected before base64 decoding."""
    gw = _make_gateway(monkeypatch, max_file_bytes=3)
    ctx = _make_context([_file_part(b"x" * 10, "application/octet-stream", "encoded-big.bin")])

    with caplog.at_level(logging.WARNING, logger="lughus.gateway"):
        objective, files = gw._extract(ctx)

    assert objective == ""
    assert files == []
    assert "encoded-big.bin" in caplog.text
    assert "encoded size" in caplog.text


def test_extract_max_files_limit(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    """Files beyond max_files are skipped with a warning."""
    gw = _make_gateway(monkeypatch, max_files=1)
    ctx = _make_context(
        [
            _file_part(b"one", "text/plain", "one.txt"),
            _file_part(b"two", "text/plain", "two.txt"),
        ]
    )

    with caplog.at_level(logging.WARNING, logger="lughus.gateway"):
        _, files = gw._extract(ctx)

    assert len(files) == 1
    assert files[0][2] == "one.txt"
    assert "max file count" in caplog.text


def test_extract_max_request_bytes_limit(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    """Total decoded file bytes are bounded per request."""
    gw = _make_gateway(monkeypatch, max_request_bytes=5)
    ctx = _make_context(
        [
            _file_part(b"abc", "text/plain", "a.txt"),
            _file_part(b"def", "text/plain", "b.txt"),
        ]
    )

    with caplog.at_level(logging.WARNING, logger="lughus.gateway"):
        _, files = gw._extract(ctx)

    assert len(files) == 1
    assert files[0][2] == "a.txt"
    assert "total decoded file bytes" in caplog.text


def test_extract_none_message(monkeypatch) -> None:
    """None message returns empty objective and empty file list."""
    gw = _make_gateway(monkeypatch)
    context = MagicMock()
    context.message = None
    objective, files = gw._extract(context)
    assert objective == ""
    assert files == []


def test_extract_original_filename_prefix(monkeypatch) -> None:
    """__ORIGINAL_FILENAME__: prefix sets the name of the next FilePart."""
    gw = _make_gateway(monkeypatch)
    raw = b"binary content"
    ctx = _make_context(
        [
            _text_part("__ORIGINAL_FILENAME__:custom_name.xlsx"),
            _file_part(raw, "application/vnd.ms-excel", "upload.bin"),
        ]
    )
    objective, files = gw._extract(ctx)
    assert objective == ""  # prefix part is consumed, not added to objective
    assert len(files) == 1
    _, _, name = files[0]
    assert name == "custom_name.xlsx"


def test_extract_sanitizes_uploaded_filename(monkeypatch) -> None:
    gw = _make_gateway(monkeypatch)
    ctx = _make_context(
        [
            _text_part("__ORIGINAL_FILENAME__:../../secret.txt"),
            _file_part(b"binary content", "text/plain", "upload.bin"),
        ]
    )

    _, files = gw._extract(ctx)

    assert files[0][2] == "secret.txt"


def test_extract_sanitizes_windows_uploaded_filename(monkeypatch) -> None:
    gw = _make_gateway(monkeypatch)
    ctx = _make_context(
        [
            _file_part(b"binary content", "text/plain", r"..\\..\\secret.txt"),
        ]
    )

    _, files = gw._extract(ctx)

    assert files[0][2] == "secret.txt"


def test_validate_artifacts_total_size_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_ARTIFACT_BYTES", "10")
    monkeypatch.setenv("MAX_TOTAL_ARTIFACT_BYTES", "5")
    settings = BaseSettings()

    with pytest.raises(ValueError, match="total max size"):
        _validate_artifacts(
            [
                Artifact(data=b"abc", mime_type="text/plain", name="a.txt"),
                Artifact(data=b"def", mime_type="text/plain", name="b.txt"),
            ],
            settings,
        )


def test_extract_sanitizes_shell_injection_characters(monkeypatch) -> None:
    gw = _make_gateway(monkeypatch)
    ctx = _make_context(
        [
            _file_part(b"binary content", "text/plain", r"foo; rm -rf ; `id`.txt"),
        ]
    )

    _, files = gw._extract(ctx)

    # All unsafe characters replaced with underscores
    assert files[0][2] == "foo__rm_-rf____id_.txt"
