"""TaskList tool — list tasks with optional filtering."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from cccode.team.manager import TeamManager
from cccode.team.tasks import TaskStore
from cccode.team.types import TeamNotFoundError
from cccode.tools.base import Tool, ToolResult


class TaskListParams(BaseModel):
    team: str = Field(..., description="Sanitised team slug.")
    status: str | None = Field(
        None,
        description="Filter by status: pending | in_progress | completed | blocked.",
    )
    assignee: str | None = Field(
        None,
        description="Filter by assignee name.",
    )


class TaskListTool(Tool):
    name: str = "TaskList"
    description: str = (
        "List tasks in the team's shared task list.  A task is considered"
        " 'ready' when all of its blocked_by dependencies are completed."
    )
    params_model: type = TaskListParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TaskListParams)
                else TaskListParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TaskList args: {exc}", is_error=True)

        try:
            team = await self._team_manager.get(p.team)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to load team: {exc}", is_error=True)

        store = TaskStore(team.config_dir)
        try:
            tasks = await store.list_(status=p.status, assignee=p.assignee)
        except Exception as exc:
            return ToolResult(output=f"Failed to list tasks: {exc}", is_error=True)

        data = []
        for t in tasks:
            d = t.to_dict()
            d["is_ready"] = getattr(t, "is_ready", True)
            data.append(d)

        if not data:
            return ToolResult(output="No matching tasks.")
        return ToolResult(output=json.dumps(data, indent=2))