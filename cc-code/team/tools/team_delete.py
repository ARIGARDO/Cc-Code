"""TeamDelete tool — delete an existing team."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mewcode.team.manager import TeamManager
from mewcode.team.types import TeamError, TeamNotFoundError
from mewcode.tools.base import Tool, ToolResult


class TeamDeleteParams(BaseModel):
    name: str = Field(
        ...,
        description="Sanitised team slug (as returned by TeamCreate or /team list).",
    )
    force: bool = Field(
        False,
        description="If true, delete even if the team has active members.",
    )


class TeamDeleteTool(Tool):
    name: str = "TeamDelete"
    description: str = (
        "Delete a team and all of its data (members, tasks, mailbox). "
        "By default deletion is refused if the team still has active members."
    )
    params_model: type = TeamDeleteParams
    category: str = "read"
    is_concurrency_safe: bool = False
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TeamDeleteParams)
                else TeamDeleteParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TeamDelete args: {exc}", is_error=True)

        try:
            await self._team_manager.delete(p.name, force=p.force)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except TeamError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to delete team: {exc}", is_error=True)

        return ToolResult(output=f"OK — team '{p.name}' deleted.")