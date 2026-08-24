"""Tests for the /ui/approvals decision endpoints (developer console)."""

from __future__ import annotations

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.testclient import TestClient

from lughus import build_app
from lughus.governance.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)
from lughus.interfaces.gateway import BaseGateway

pytestmark = pytest.mark.extra_server


class ApprovingGateway(BaseGateway):
    """Gateway exposing a real InMemoryApprovalStore."""

    def __init__(self) -> None:
        from lughus import BaseSettings

        super().__init__(llm=None, settings=BaseSettings())
        self.approval_store = InMemoryApprovalStore()

    async def handle(self, objective, files):
        yield  # pragma: no cover - generator formality


def _client(gateway: BaseGateway) -> TestClient:
    card = AgentCard(
        name="t",
        description="",
        url="http://test",
        version="0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=[],
        default_output_modes=[],
        skills=[AgentSkill(id="s", name="s", description="", tags=[])],
        preferred_transport="JSONRPC",
        protocol_version="0.3.0",
    )
    app = build_app(card, gateway, setup_otel=False, enable_console=True)
    return TestClient(app)


def _seed_request(store: InMemoryApprovalStore, run_id: str = "run-1") -> ApprovalRequest:
    request = ApprovalRequest(
        run_id=run_id,
        tool_name="delete_file",
        proposal_hash=proposal_digest("delete_file", {"path": "a.txt"}),
        risk="high",
    )
    # synchronous store despite the async API: drive it directly.
    store._items[request.request_id] = request
    return request


def test_decision_endpoint_records_approval() -> None:
    gateway = ApprovingGateway()
    approval = _seed_request(gateway.approval_store)

    with _client(gateway) as client:
        resp = client.post(
            f"/ui/approvals/{approval.request_id}",
            json={"approved": True},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == "ui-operator"


def test_decision_endpoint_records_rejection() -> None:
    gateway = ApprovingGateway()
    approval = _seed_request(gateway.approval_store)

    with _client(gateway) as client:
        resp = client.post(
            f"/ui/approvals/{approval.request_id}",
            json={"approved": False, "subject": "reviewer-7"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    record = gateway.approval_store._items[approval.request_id]
    assert record.status == ApprovalStatus.REJECTED
    assert record.decided_by == "reviewer-7"


def test_decision_endpoint_validates_payload() -> None:
    gateway = ApprovingGateway()
    approval = _seed_request(gateway.approval_store)

    with _client(gateway) as client:
        missing_bool = client.post(f"/ui/approvals/{approval.request_id}", json={})
        unknown = client.post("/ui/approvals/does-not-exist", json={"approved": True})
    assert missing_bool.status_code == 400
    assert unknown.status_code == 404


def test_get_endpoint_reports_pending_status() -> None:
    gateway = ApprovingGateway()
    approval = _seed_request(gateway.approval_store)

    with _client(gateway) as client:
        resp = client.get(f"/ui/approvals/{approval.request_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["tool_name"] == "delete_file"
