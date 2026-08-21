"""Interface layer: server, gateway, UI, CLI, MCP."""

from .gateway import BaseGateway
from .mcp import MCPAdapter, MCPClient, MCPServerConfig, MCPToolDescriptor
from .server import BoundedInMemoryTaskStore, ProductionGuardMiddleware, build_app, serve
from .ui_server import shutdown_ui_server

__all__ = [
    "BaseGateway",
    "BoundedInMemoryTaskStore",
    "MCPAdapter",
    "MCPClient",
    "MCPServerConfig",
    "MCPToolDescriptor",
    "ProductionGuardMiddleware",
    "build_app",
    "serve",
    "shutdown_ui_server",
]
