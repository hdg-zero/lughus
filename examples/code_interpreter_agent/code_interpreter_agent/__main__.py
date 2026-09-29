"""Entrypoint for the Sandboxed Data Scientist / Code Interpreter Agent service."""

from __future__ import annotations

import logging

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from lughus import LLM, build_app, serve

from .config import Settings
from .gateway import CodeInterpreterGateway

settings = Settings()
logging.basicConfig(level=settings.log_level.upper())

agent_card = AgentCard(
    name=settings.agent_name,
    version="0.22.0",
    url=settings.public_url or f"http://{settings.host}:{settings.port}",
    description=settings.agent_description,
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="sandboxed-python-interpreter",
            name="Sandboxed Python & Data Science",
            description=(
                "Executes Python and data-science code inside a fail-closed OCI sandbox, "
                "then exports bounded binary artifacts."
            ),
            tags=["python", "docker", "sandbox", "data-science", "matplotlib"],
        )
    ],
    capabilities=AgentCapabilities(streaming=True),
)

llm = LLM.from_settings(settings)
gateway = CodeInterpreterGateway(llm=llm, settings=settings)

# ASGI application for uvicorn
app = build_app(
    agent_card=agent_card,
    gateway=gateway,
    enable_console=settings.enable_console,
)


def main() -> None:
    """Run the Code Interpreter Agent uvicorn server."""
    serve(
        agent_card=agent_card,
        gateway=gateway,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        enable_console=settings.enable_console,
    )


if __name__ == "__main__":
    main()
