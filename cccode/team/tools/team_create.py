"""TeamCreate tool — create a new team and return the sanitized slug."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cccode.team.manager import TeamManager, sanitize
from cccode.team.types import TeamExistsError
from cccode.tools.base import Tool, ToolResult


class TeamCreateParams(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Human-readable team name (will be sanitised to a path).",
    )
    description: str = Field(
        "",
        max_length=1000,
        description="Optional one-sentence description of the team's goal.",
    )


class TeamCreateTool(Tool):
    name: str = "TeamCreate"
    description: str = (
        "Create a new named team.  Members and shared tasks live inside "
        "the team for the duration of the conversation.  A team must "
        "exist before you can use TeamDelete / TaskCreate / SendMessage."
    )
    params_model: type = TeamCreateParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TeamCreateParams)
                else TeamCreateParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TeamCreate args: {exc}", is_error=True)

        try:
            team = await self._team_manager.create(p.name, p.description)
        except TeamExistsError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to create team: {exc}", is_error=True)

        return ToolResult(
            output=(
                f"OK — team '{team.name}' created (slug='{team.sanitized_name}', "
                f"backend={team.backend}).  Use this slug for TeamDelete, "
                f"TaskCreate, TaskGet, TaskList, TaskUpdate, and SendMessage."
            )
        )