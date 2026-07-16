"""Four-layer tool filtering for sub-agents."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "Agent",
    "AskUserQuestion",
})

ASYNC_AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "ReadFile",
    "WebSearch",
    "TodoWrite",
    "Grep",
    "WebFetch",
    "Glob",
    "Bash",
    "EditFile",
    "WriteFile",
    "NotebookEdit",
    "Skill",
    "LoadSkill",
    "SyntheticOutput",
    "ToolSearch",
    "EnterWorktree",
    "ExitWorktree",
})

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: frozenset[str] = ASYNC_AGENT_ALLOWED_TOOLS | frozenset({
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "CronCreate",
    "CronDelete",
    "CronList",
})


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__")


def resolve_agent_tools(
    registry: Any,
    definition: Any,
    is_background: bool = False,
) -> list[str]:
    """Apply four-layer tool filtering and return allowed tool names.

    Layer 1: MCP tools always pass through.
    Layer 2: Global disallowed (ALL_AGENT_DISALLOWED_TOOLS).
    Layer 3: Custom agent extra restrictions (CUSTOM_AGENT_DISALLOWED_TOOLS)
             for source in {project, user, plugin}.
    Layer 4: Background whitelist (ASYNC_AGENT_ALLOWED_TOOLS) when
             is_background=True.
    Layer 5: Definition-level disallowed_tools blacklist + tools whitelist.
    """
    all_names = set(registry.list_tool_names())

    allowed: set[str] = set()

    for name in all_names:
        if _is_mcp_tool(name):
            allowed.add(name)
            continue

        if name in ALL_AGENT_DISALLOWED_TOOLS:
            continue

        source = getattr(definition, "source", "builtin")
        if source in ("project", "user", "plugin"):
            if name in CUSTOM_AGENT_DISALLOWED_TOOLS:
                continue

        if is_background:
            if name not in ASYNC_AGENT_ALLOWED_TOOLS and not _is_mcp_tool(name):
                continue

        disallowed = set(getattr(definition, "disallowed_tools", []) or [])
        if name in disallowed:
            continue

        tools_whitelist = set(getattr(definition, "tools", []) or [])
        if tools_whitelist and name not in tools_whitelist:
            continue

        allowed.add(name)

    return sorted(allowed)