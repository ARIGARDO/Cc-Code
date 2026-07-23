"""Configuration validators."""

from __future__ import annotations

from mewcode.config import ConfigError, MCPServerConfig


def validate_mcp_server_config(cfg: MCPServerConfig) -> None:
    """Validate a single :class:`MCPServerConfig`.

    Raises :class:`ConfigError` if both *command* and *url* are set, or if
    neither is set.
    """
    if cfg.command is not None and cfg.url is not None:
        raise ConfigError(
            f"MCP server '{cfg.name}' cannot have both command and url"
        )
    if cfg.command is None and cfg.url is None:
        raise ConfigError(
            f"MCP server '{cfg.name}' must have either command or url"
        )