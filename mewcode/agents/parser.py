"""Agent definition parser: AgentDef dataclass, frontmatter parsing, validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_MODELS = {"inherit", "sonnet", "opus", "haiku", ""}
VALID_PERMISSION_MODES = {"default", "acceptEdits", "dontAsk", ""}
VALID_ISOLATION_MODES = {"", "worktree"}


class AgentParseError(Exception):
    pass


@dataclass
class AgentDef:
    agent_type: str = ""
    when_to_use: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 50
    permission_mode: str = "default"
    background: bool = False
    isolation: str = ""
    file_path: str = ""
    source: str = "builtin"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse ``---\\nyaml\\n---\\nbody`` into (frontmatter_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    yaml_str = text[3:end].strip()
    body = text[end + 3:].strip()
    import yaml
    try:
        fm = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as e:
        raise AgentParseError(f"YAML parse error: {e}") from e
    return fm, body


def _validate_agent_meta(fm: dict[str, Any], tag: str) -> None:
    """Validate required fields and value ranges in frontmatter."""
    if not fm.get("name"):
        raise AgentParseError(f"agent '{tag}': 'name' is required")
    if not fm.get("description"):
        raise AgentParseError(f"agent '{tag}': 'description' is required")

    model = fm.get("model", "inherit")
    if model and model not in VALID_MODELS:
        raise AgentParseError(
            f"agent '{tag}': invalid model '{model}', must be one of {sorted(VALID_MODELS)}"
        )

    pm = fm.get("permissionMode", "")
    if pm and pm not in VALID_PERMISSION_MODES:
        raise AgentParseError(
            f"agent '{tag}': invalid permissionMode '{pm}', must be one of {sorted(VALID_PERMISSION_MODES)}"
        )

    iso = fm.get("isolation", "")
    if iso and iso not in VALID_ISOLATION_MODES:
        raise AgentParseError(
            f"agent '{tag}': invalid isolation '{iso}', must be one of {sorted(VALID_ISOLATION_MODES)}"
        )

    mt = fm.get("maxTurns", 50)
    if not isinstance(mt, int) or mt <= 0:
        raise AgentParseError(
            f"agent '{tag}': maxTurns must be a positive integer, got {mt!r}"
        )


def parse_agent_file(path: Path, source: str = "builtin") -> AgentDef:
    """Parse an agent definition Markdown file into an ``AgentDef``."""
    text = path.read_text(encoding="utf-8")
    tag = path.stem
    fm, body = parse_frontmatter(text)
    _validate_agent_meta(fm, tag)

    return AgentDef(
        agent_type=fm.get("name", tag),
        when_to_use=fm.get("description", ""),
        system_prompt=body,
        tools=list(fm.get("tools", []) or []),
        disallowed_tools=list(fm.get("disallowedTools", []) or []),
        model=fm.get("model", "inherit"),
        max_turns=fm.get("maxTurns", 50),
        permission_mode=fm.get("permissionMode", "default"),
        background=bool(fm.get("background", False)),
        isolation=fm.get("isolation", ""),
        file_path=str(path),
        source=source,
    )