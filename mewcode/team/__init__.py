"""Team module — multi-agent collaboration for mewcode.

See :mod:`mewcode.team.manager` and :mod:`mewcode.coordinator` for the
public surface.
"""

from __future__ import annotations

from mewcode.team.manager import TeamManager
from mewcode.team.registry import AgentNameRegistry
from mewcode.team.types import BackendType, TeammateInfo, Team
from mewcode.team.tools import TEAM_TOOL_NAMES, build_team_tools, is_team_tool

__all__ = [
    "TeamManager",
    "AgentNameRegistry",
    "BackendType",
    "TeammateInfo",
    "Team",
    "TEAM_TOOL_NAMES",
    "build_team_tools",
    "is_team_tool",
]