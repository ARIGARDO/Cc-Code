"""Team module — multi-agent collaboration for cccode.

See :mod:`cccode.team.manager` and :mod:`cccode.coordinator` for the
public surface.
"""

from __future__ import annotations

from cccode.team.manager import TeamManager
from cccode.team.registry import AgentNameRegistry
from cccode.team.types import BackendType, TeammateInfo, Team
from cccode.team.tools import TEAM_TOOL_NAMES, build_team_tools, is_team_tool

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