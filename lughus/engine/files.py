"""File validation and safe Base64 decoding utilities."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..infra._threading import run_sync_in_thread

__all__ = ["_safe_filename", "decode_file_bytes", "decode_files_payload"]


def _safe_filename(name: str | None) -> str:
    """Return a path-free filename suitable for handing to agent code."""
    value = (name or "file").replace("\\", "/")
    filename = os.path.basename(value).replace("\x00", "").strip()
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    if filename in {"", ".", ".."}:
        return "file"
    return filename


async def decode_file_bytes(
    raw_base64: str | bytes,
    name: str | None,
    mime_type: str | None,
    settings: Any,
    executor: ThreadPoolExecutor | None = None,
) -> tuple[bytes, str, str]:
    """Decode a single Base64 encoded file payload with size checks."""
    safe_name = _safe_filename(name)
    safe_mime = (mime_type or "application/octet-stream").strip()

    if isinstance(raw_base64, str):
        enc_bytes = raw_base64.encode("ascii", errors="ignore")
    else:
        enc_bytes = raw_base64

    def _decode_enc(s: bytes = enc_bytes) -> bytes:
        return base64.b64decode(s, validate=True)

    try:
        if executor is not None:
            data = await run_sync_in_thread(
                _decode_enc,
                executor=executor,
            )
        else:
            data = await asyncio.to_thread(_decode_enc)
    except (binascii.Error, OSError) as exc:
        raise ValueError("files is not valid base64") from exc

    max_file_bytes = getattr(settings, "max_file_bytes", 25 * 1024 * 1024)
    if len(data) > max_file_bytes:
        raise ValueError(f"File '{safe_name}' exceeds max size {max_file_bytes} bytes")

    return data, safe_mime, safe_name


async def decode_files_payload(
    raw_files: Any,
    settings: Any,
    executor: ThreadPoolExecutor | None = None,
) -> list[tuple[bytes, str, str]]:
    """Decode and validate a list of Base64 file objects from a request body."""
    if raw_files is None:
        return []
    if not isinstance(raw_files, list):
        raise ValueError("files must be a list")

    max_files = getattr(settings, "max_files", 10)
    if len(raw_files) > max_files:
        raise ValueError(f"Too many files: max {max_files}")

    max_request_bytes = getattr(settings, "max_request_bytes", 50 * 1024 * 1024)
    files: list[tuple[bytes, str, str]] = []
    total_bytes = 0

    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ValueError(f"files[{index}] must be an object")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise ValueError(f"files[{index}].content_base64 must be a string")

        max_file_bytes = getattr(settings, "max_file_bytes", 25 * 1024 * 1024)
        max_encoded_chars = ((max_file_bytes + 2) // 3) * 4
        if len(encoded) > max_encoded_chars:
            safe_name = _safe_filename(item.get("name"))
            raise ValueError(f"File '{safe_name}' exceeds max size {max_file_bytes} bytes")

        try:
            data, mime, name = await decode_file_bytes(
                encoded,
                item.get("name"),
                item.get("mime_type"),
                settings,
                executor=executor,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "files is not valid base64":
                raise ValueError(f"files[{index}] is not valid base64") from exc
            raise

        total_bytes += len(data)
        if total_bytes > max_request_bytes:
            raise ValueError(f"Files exceed max request size {max_request_bytes} bytes")
        files.append((data, mime, name))
    return files
