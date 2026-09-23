"""End-to-end offline tests for DataIngestionGateway using MockLLM."""

from __future__ import annotations

import pytest
from data_ingestion_agent.config import Settings
from data_ingestion_agent.database import init_demo_database
from data_ingestion_agent.gateway import DataIngestionGateway

from lughus import CompletionEvent, ProgressEvent
from lughus.testing import MockLLM


@pytest.fixture(autouse=True)
def setup_database(tmp_path, monkeypatch):
    db_path = tmp_path / "test_data.db"
    init_demo_database(db_path)
    monkeypatch.setattr("data_ingestion_agent.tools.DEFAULT_DB_PATH", db_path)


@pytest.mark.asyncio
async def test_gateway_flow_with_mock_llm(tmp_path):
    settings = Settings(database_path=tmp_path / "test_data.db")
    mock_llm = MockLLM(
        [
            [{"id": "call_1", "name": "list_tables", "arguments": {}}],
            "Database contains orders, warehouses, customers, and fulfillment_delays.",
        ]
    )

    gateway = DataIngestionGateway(llm=mock_llm, settings=settings)

    events = []
    async for event in gateway.handle("Please list the available tables.", files=[]):
        events.append(event)

    assert any(isinstance(e, ProgressEvent) for e in events)
    completion = next(e for e in events if isinstance(e, CompletionEvent))
    assert "Database contains orders" in completion.text
    assert completion.metadata["iterations"] == 2
