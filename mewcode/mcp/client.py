"""Single-server MCP client.

Wraps the official ``mcp`` SDK ``ClientSession`` with stdio / Streamable HTTP
transport selection. The entire transport + session lifecycle is managed by an
:class:`AsyncExitStack` so cleanup is deterministic.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from mewcode.config import MCPServerConfig, build_child_env, resolve_env_vars

logger = logging.getLogger(__name__)


class MCPClient:
    """Single MCP server session handle."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.name = config.name
        self._session: Optional[ClientSession] = None
        self._stack: Optional[AsyncExitStack] = None
        self._alive: bool = False

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def connect(self) -> None:
        """Establish transport + initialize session."""
        self._stack = AsyncExitStack()
        try:
            if self.config.is_stdio:
                await self._connect_stdio()
            else:
                await self._connect_http()
            assert self._session is not None
            await self._session.initialize()
            self._alive = True
        except Exception:
            await self._cleanup_stack()
            raise

    async def _connect_stdio(self) -> None:
        params = StdioServerParameters(
            command=self.config.command,  # type: ignore[arg-type]
            args=list(self.config.args),
            env=build_child_env(self.config.env),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))  # type: ignore[union-attr]
        self._session = await self._stack.enter_async_context(  # type: ignore[union-attr]
            ClientSession(read, write)
        )

    async def _connect_http(self) -> None:
        import httpx

        headers = {k: resolve_env_vars(v) for k, v in self.config.headers.items()}
        http_client = await self._stack.enter_async_context(  # type: ignore[union-attr]
            httpx.AsyncClient(headers=headers)
        )
        transport_ctx = streamable_http_client(
            self.config.url,  # type: ignore[arg-type]
            http_client=http_client,
        )
        read, write, _get_session_id = await self._stack.enter_async_context(  # type: ignore[union-attr]
            transport_ctx
        )
        self._session = await self._stack.enter_async_context(  # type: ignore[union-attr]
            ClientSession(read, write)
        )

    async def list_tools(self) -> list[types.Tool]:
        """Return the tool list advertised by the server."""
        assert self._session is not None
        result = await self._session.list_tools()
        return result.tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """Invoke *name* on the server, returning the raw ``CallToolResult``."""
        assert self._session is not None
        return await self._session.call_tool(name, arguments)

    async def close(self) -> None:
        """Tear down the session and transport."""
        self._alive = False
        await self._cleanup_stack()

    async def _cleanup_stack(self) -> None:
        """Close the ``AsyncExitStack``, swallowing anyio cancel-scope races."""
        if self._stack is None:
            return
        stack = self._stack
        self._stack = None
        self._session = None
        try:
            await stack.aclose()
        except RuntimeError as e:
            msg = str(e).lower()
            if "cancel scope" in msg:
                return
            logger.debug("MCPClient[%s] cleanup error: %s", self.name, e)
        except Exception as e:
            logger.debug("MCPClient[%s] cleanup error: %s", self.name, e)