"""TaskGet tool — retrieve a single task by id."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mewcode.team.manager import TeamManager
from mewcode.team.tasks import TaskStore
from mewcode.team.types import TeamNotFoundError
from mewcode.tools.base import Tool, ToolResult


class TaskGetParams(BaseModel):
    team: str = Field(..., description="Sanitised team slug.")
    task_id: str = Field(..., description="The task_<hex> identifier.")


class TaskGetTool(Tool):
    name: str = "TaskGet"
    description: str = (
        "Fetch a single task by id.  Returns the full task object "
        "(title, description, status, assignee, blocked_by, blocks)."
    )
    params_model: type = TaskGetParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TaskGetParams)
                else TaskGetParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TaskGet args: {exc}", is_error=True)

        try:
            team = await self._team_manager.get(p.team)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to load team: {exc}", is_error=True)

        store = TaskStore(team.config_dir)
        try:
            task = await store.get(p.task_id)
        except Exception as exc:
            return ToolResult(output=f"Failed to read task: {exc}", is_error=True)

        if task is None:
            return ToolResult(
                output=f"Task '{p.task_id}' not found in team '{p.team}'.",
                is_error=True,
            )

        data = task.to_dict()
        return ToolResult(
            output=json.dumps(data, indent=2)
        )