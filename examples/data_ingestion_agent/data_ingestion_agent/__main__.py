"""Entrypoint for the Data Ingestion Agent service."""

from __future__ import annotations

import logging
import sys

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from lughus import LLM, build_app, serve

from .config import Settings
from .database import init_demo_database
from .gateway import DataIngestionGateway

logging.basicConfig(level=logging.INFO)
settings = Settings()

agent_card = AgentCard(
    name=settings.agent_name,
    version="0.22.0",
    url=f"http://{settings.host}:{settings.port}",
    description=settings.agent_description,
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="data-ingestion-sql",
            name="SQL Data Ingestion & Profiling",
            description=(
                "Inspects schemas, samples tables, and executes read-only queries with zero leak."
            ),
            tags=["sql", "database", "zero-leak", "pydantic"],
        )
    ],
    capabilities=AgentCapabilities(streaming=True),
)

llm = LLM.from_settings(settings)
gateway = DataIngestionGateway(llm=llm, settings=settings)

# ASGI application for uvicorn
app = build_app(
    agent_card=agent_card,
    gateway=gateway,
    setup_otel=False,
    enable_console=settings.enable_console,
)


def main() -> None:
    """Run the Data Ingestion Agent uvicorn server or seed demo database."""
    if "--seed" in sys.argv:
        db_path = init_demo_database(settings.database_path)
        print(f"✅ Demo SQLite database seeded successfully at: {db_path}")
        return

    serve(
        agent_card=agent_card,
        gateway=gateway,
        host=settings.host,
        port=settings.port,
        setup_otel=False,
        enable_console=settings.enable_console,
    )


if __name__ == "__main__":
    main()
