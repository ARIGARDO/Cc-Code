"""Multi-server MCP manager."""

from __future__ import annotations

import logging
from typing import Any, Optional

from cccode.config import MCPServerConfig
from cccode.mcp.client import MCPClient
from cccode.mcp.tool_wrapper import MCPToolWrapper

logger = logging.getLogger(__name__)


class MCPManager:
    """Owns multiple :class:`MCPClient` instances and registers their tools."""

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        """Store configs keyed by server name."""
        for cfg in configs:
            self._configs[cfg.name] = cfg

    async def register_all_tools(self, registry: Any) -> list[str]:
        """Connect every configured server and register its tools.

        Returns a list of error messages (empty on full success). A single
        server failure does not block the others.
        """
        errors: list[str] = []
        for name, cfg in self._configs.items():
            try:
                client = MCPClient(cfg)
                await client.connect()
                tools = await client.list_tools()
                self._clients[name] = client
                for tool_def in tools:
                    wrapper = MCPToolWrapper(name, tool_def, client)
                    registry.register(wrapper)
                    logger.info("Registered MCP tool: %s", wrapper.name)
                logger.info("MCP server '%s' connected, %d tools", name, len(tools))
            except Exception as e:
                msg = f"MCP server '{name}' failed to connect: {e}"
                logger.warning(msg)
                errors.append(msg)
        return errors

    def get_client(self, name: str) -> Optional[MCPClient]:
        """Return the client for *name*, lazily connecting / reconnecting."""
        cfg = self._configs.get(name)
        if cfg is None:
            return None
        client = self._clients.get(name)
        if client is not None and client.is_alive:
            return client
        client = MCPClient(cfg)
        self._clients[name] = client
        return client

    async def shutdown(self) -> None:
        """Close all clients. Idempotent; errors are only logged."""
        for name, client in list(self._clients.items()):
            try:
                await client.close()
            except Exception as e:
                logger.debug("MCPManager shutdown error for '%s': %s", name, e)
        self._clients.clear()