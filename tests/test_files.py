"""Unit tests for lughus.engine.files module."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from lughus.engine.files import _safe_filename, decode_file_bytes, decode_files_payload


def test_safe_filename() -> None:
    """Verify filename sanitization, path stripping, and edge cases."""
    assert _safe_filename(None) == "file"
    assert _safe_filename("") == "file"
    assert _safe_filename(".") == "file"
    assert _safe_filename("..") == "file"
    assert _safe_filename("...") == "..."
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename(r"C:\Users\Admin\doc.pdf") == "doc.pdf"
    assert _safe_filename("foo\x00bar.txt") == "foobar.txt"
    assert _safe_filename("test file (1).png") == "test_file__1_.png"


@pytest.mark.asyncio
async def test_decode_file_bytes_with_str_and_bytes() -> None:
    """Decode valid base64 payloads passed as string or bytes."""
    settings = SimpleNamespace(max_file_bytes=1024)
    data = b"hello world"
    b64_str = base64.b64encode(data).decode("ascii")
    b64_bytes = base64.b64encode(data)

    res1 = await decode_file_bytes(b64_str, "test.txt", "text/plain", settings)
    assert res1 == (data, "text/plain", "test.txt")

    res2 = await decode_file_bytes(b64_bytes, None, None, settings)
    assert res2 == (data, "application/octet-stream", "file")


@pytest.mark.asyncio
async def test_decode_file_bytes_with_executor() -> None:
    """Decode base64 using an explicit thread pool executor."""
    settings = SimpleNamespace(max_file_bytes=1024)
    data = b"executor test"
    b64 = base64.b64encode(data).decode("ascii")
    with ThreadPoolExecutor(max_workers=1) as pool:
        res = await decode_file_bytes(b64, "exec.txt", "text/plain", settings, executor=pool)
    assert res[0] == data


@pytest.mark.asyncio
async def test_decode_file_bytes_invalid_base64() -> None:
    """Invalid base64 payload raises ValueError."""
    settings = SimpleNamespace(max_file_bytes=1024)
    with pytest.raises(ValueError, match="files is not valid base64"):
        await decode_file_bytes("not-valid-base64!!!", "bad.bin", None, settings)


@pytest.mark.asyncio
async def test_decode_file_bytes_size_exceeded() -> None:
    """Decoded content exceeding max_file_bytes raises ValueError."""
    settings = SimpleNamespace(max_file_bytes=5)
    b64 = base64.b64encode(b"too long data").decode("ascii")
    with pytest.raises(ValueError, match="exceeds max size 5 bytes"):
        await decode_file_bytes(b64, "big.txt", None, settings)


@pytest.mark.asyncio
async def test_decode_files_payload_validation() -> None:
    """Validate structure, bounds, and decoding of multi-file payloads."""
    settings = SimpleNamespace(
        max_files=2,
        max_file_bytes=20,
        max_request_bytes=30,
    )

    # None returns empty list
    assert await decode_files_payload(None, settings) == []

    # Non-list raises ValueError
    with pytest.raises(ValueError, match="files must be a list"):
        await decode_files_payload("not-a-list", settings)

    # Exceeding max_files
    with pytest.raises(ValueError, match="Too many files: max 2"):
        await decode_files_payload([{}, {}, {}], settings)

    # Item not a dict
    with pytest.raises(ValueError, match=r"files\[0\] must be an object"):
        await decode_files_payload(["not-a-dict"], settings)

    # Missing or non-string content_base64
    with pytest.raises(ValueError, match=r"files\[0\]\.content_base64 must be a string"):
        await decode_files_payload([{"name": "a.txt"}], settings)
    with pytest.raises(ValueError, match=r"files\[0\]\.content_base64 must be a string"):
        await decode_files_payload([{"content_base64": 123}], settings)

    # Decoded size exceeded inside decode_file_bytes
    tiny_settings = SimpleNamespace(max_files=5, max_file_bytes=1, max_request_bytes=100)
    with pytest.raises(ValueError, match="exceeds max size 1 bytes"):
        await decode_files_payload([{"content_base64": "AAAA"}], tiny_settings)

    # Pre-decode length guard
    with pytest.raises(ValueError, match="exceeds max size 20 bytes"):
        await decode_files_payload([{"content_base64": "A" * 200, "name": "huge.txt"}], settings)

    # Invalid base64 in payload
    with pytest.raises(ValueError, match=r"files\[0\] is not valid base64"):
        await decode_files_payload([{"content_base64": "not-valid!!!"}], settings)

    # Total request size exceeded
    f1 = {"content_base64": base64.b64encode(b"123456789012345").decode("ascii")}
    f2 = {"content_base64": base64.b64encode(b"12345678901234567890").decode("ascii")}
    with pytest.raises(ValueError, match="Files exceed max request size 30 bytes"):
        await decode_files_payload([f1, f2], settings)

    # Successful multi-file decode
    ok1 = {"content_base64": base64.b64encode(b"file1").decode("ascii"), "name": "f1.txt"}
    ok2 = {
        "content_base64": base64.b64encode(b"file2").decode("ascii"),
        "name": "f2.txt",
        "mime_type": "text/plain",
    }
    results = await decode_files_payload([ok1, ok2], settings)
    assert len(results) == 2
    assert results[0] == (b"file1", "application/octet-stream", "f1.txt")
    assert results[1] == (b"file2", "text/plain", "f2.txt")
