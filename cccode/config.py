import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional


class ConfigError(Exception):
    """Raised when configuration is invalid."""


@dataclass
class ProviderConfig:
    name: str = ""
    protocol: str = "anthropic"
    base_url: Optional[str] = None
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    thinking: bool = True

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.protocol == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        elif self.protocol == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        return ""

    def get_max_output_tokens(self) -> int:
        if self.thinking:
            return 64000
        return 8192


# ──────────────────────────────────────────────
#  ENV helpers (T1)
# ──────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Whitelist of host env vars to pass through to child processes
_ENV_WHITELIST: frozenset[str] = frozenset({"PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TERM"})


def resolve_env_vars(text: str) -> str:
    """Expand ``${VAR}`` references using ``os.environ``.

    Missing variables keep their ``${VAR}`` placeholder.
    """
    def _repl(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), m.group(0))

    return _ENV_VAR_RE.sub(_repl, text)


def build_child_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build a child-process env with a whitelist, plus any *extra* overrides.

    Host secrets (e.g. ``ANTHROPIC_API_KEY``) are NOT carried over.
    """
    env: dict[str, str] = {}
    for key in _ENV_WHITELIST:
        if key in os.environ:
            env[key] = os.environ[key]
    if extra:
        for k, v in extra.items():
            env[k] = resolve_env_vars(v)
    return env


# ──────────────────────────────────────────────
#  MCP server config (T1)
# ──────────────────────────────────────────────

@dataclass
class MCPServerConfig:
    name: str = ""
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    url: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_stdio(self) -> bool:
        return self.command is not None


# ──────────────────────────────────────────────
#  AppConfig + load_config (T2)
# ──────────────────────────────────────────────

@dataclass
class AppConfig:
    providers: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    raw_hooks: list[dict[str, Any]] = field(default_factory=list)


def _parse_mcp_servers(raw: Any) -> list[MCPServerConfig]:
    from cccode.validator import validate_mcp_server_config

    if not raw:
        return []

    items: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for name, val in raw.items():
            entry = dict(val) if val else {}
            entry.setdefault("name", name)
            items.append(entry)
    elif isinstance(raw, list):
        for entry in raw:
            items.append(dict(entry) if entry else {})
    else:
        raise ConfigError("mcp_servers must be a list or mapping")

    result: list[MCPServerConfig] = []
    for item in items:
        cfg = MCPServerConfig(
            name=item.get("name", ""),
            command=item.get("command"),
            args=list(item.get("args", []) or []),
            url=item.get("url"),
            headers=dict(item.get("headers", {}) or {}),
            env=dict(item.get("env", {}) or {}),
        )
        validate_mcp_server_config(cfg)
        result.append(cfg)
    return result


def load_config(path: Any) -> AppConfig:
    """Load YAML config from *path* into an :class:`AppConfig`."""
    import yaml
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return AppConfig()

    with open(p) as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(
        providers=list(raw.get("providers", []) or []),
        mcp_servers=_parse_mcp_servers(raw.get("mcp_servers")),
        raw_hooks=list(raw.get("hooks", []) or []),
    )