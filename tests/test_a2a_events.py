"""Tests for the a2a_request / a2a_response console events."""

from __future__ import annotations

import base64

import pytest

from lughus.loop import collect_tool_events, emit_a2a_request, emit_a2a_response


def test_emit_a2a_request_carries_objective_and_target() -> None:
    events: list[dict] = []
    with collect_tool_events(events.append):
        emit_a2a_request(
            target_agent="research_agent",
            url="http://localhost:9001",
            objective="Find papers on RAG",
        )
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "a2a_request"
    assert event["target_agent"] == "research_agent"
    assert event["url"] == "http://localhost:9001"
    assert event["method"] == "message/send"
    assert event["objective"] == "Find papers on RAG"
    assert event["file_count"] == 0
    assert event["files"] == []


def test_emit_a2a_request_lists_attached_files() -> None:
    events: list[dict] = []
    with collect_tool_events(events.append):
        emit_a2a_request(
            target_agent="agent",
            url="http://x",
            objective="obj",
            files=[(b"data", "text/plain", "notes.txt")],
        )
    assert events[0]["file_count"] == 1
    assert events[0]["files"] == [{"name": "notes.txt", "mime_type": "text/plain", "size_bytes": 4}]


def test_emit_a2a_response_encodes_artifacts_as_base64() -> None:
    events: list[dict] = []
    with collect_tool_events(events.append):
        emit_a2a_response(
            target_agent="report_agent",
            url="http://localhost:9002",
            text="Final report body",
            artifacts=[(b"PDFBYTES", "application/pdf", "report.pdf")],
            remote_task_id="task_42",
            elapsed_ms=123.456,
        )
    event = events[0]
    assert event["type"] == "a2a_response"
    assert event["status"] == "ok"
    assert event["text"] == "Final report body"
    assert event["remote_task_id"] == "task_42"
    assert event["elapsed_ms"] == 123.46
    (artifact,) = event["artifacts"]
    assert artifact["name"] == "report.pdf"
    assert artifact["mime_type"] == "application/pdf"
    assert base64.b64decode(artifact["data_base64"]) == b"PDFBYTES"


def test_emit_a2a_response_error_shape() -> None:
    events: list[dict] = []
    with collect_tool_events(events.append):
        emit_a2a_response(
            target_agent="agent",
            url="http://x",
            status="error",
            error_code="DELEGATION_TIMEOUT",
        )
    event = events[0]
    assert event["status"] == "error"
    assert event["error_code"] == "DELEGATION_TIMEOUT"
    assert event["text"] == ""
    assert event["artifacts"] == []


def test_no_sink_is_silent() -> None:
    # Must not raise when no collection context is active.
    emit_a2a_request(target_agent="a", url="http://x", objective="o")
    emit_a2a_response(target_agent="a", url="http://x")


@pytest.mark.parametrize("fn", [emit_a2a_request, emit_a2a_response])
def test_event_types_are_json_serializable(fn) -> None:
    import json

    events: list[dict] = []
    with collect_tool_events(events.append):
        if fn is emit_a2a_request:
            fn(target_agent="a", url="http://x", objective="o")
        else:
            fn(target_agent="a", url="http://x", text="t")
    json.dumps(events)  # must not raise
