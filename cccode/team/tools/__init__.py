"""Convenience helpers for constructing the default team tool set."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cccode.tools.base import Tool

if TYPE_CHECKING:
    from cccode.team.manager import TeamManager
    from cccode.team.registry import AgentNameRegistry


def build_team_tools(
    team_manager: "TeamManager",
    registry: "AgentNameRegistry | None" = None,
    current_member: str = "lead",
) -> list[Tool]:
    """Return the canonical set of team-aware tools.

    *   TeamCreate / TeamDelete — life-cycle ops.
    *   TaskCreate / TaskGet / TaskList / TaskUpdate — shared tasks.
    *   SendMessage — inter-agent text + control messages.
    """

    # local imports to avoid import cycles when the package is first loaded
    from cccode.team.tools.team_create import TeamCreateTool
    from cccode.team.tools.team_delete import TeamDeleteTool
    from cccode.team.tools.task_create import TaskCreateTool
    from cccode.team.tools.task_get import TaskGetTool
    from cccode.team.tools.task_list import TaskListTool
    from cccode.team.tools.task_update import TaskUpdateTool
    from cccode.team.tools.send_message import SendMessageTool

    return [
        TeamCreateTool(team_manager),
        TeamDeleteTool(team_manager),
        TaskCreateTool(team_manager),
        TaskGetTool(team_manager),
        TaskListTool(team_manager),
        TaskUpdateTool(team_manager),
        SendMessageTool(team_manager, registry=registry, current_member=current_member),
    ]


TEAM_TOOL_NAMES: list[str] = [
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
]


def is_team_tool(name: str) -> bool:
    return name in TEAM_TOOL_NAMES