"""TaskCreate tool — add a task to the shared team task list."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mewcode.team.manager import TeamManager
from mewcode.team.tasks import TaskStore
from mewcode.team.types import TeamNotFoundError
from mewcode.tools.base import Tool, ToolResult


class TaskCreateParams(BaseModel):
    team: str = Field(..., description="Sanitised team slug.")
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Short task title shown in summaries.",
    )
    description: str = Field(
        "",
        max_length=4000,
        description="Longer description, requirements, context.",
    )
    assignee: str = Field(
        "",
        max_length=64,
        description="Optional member name for who should tackle this task.",
    )
    blocked_by: list[str] | None = Field(
        default=None,
        description="List of task_ids that must be completed first.",
    )


class TaskCreateTool(Tool):
    name: str = "TaskCreate"
    description: str = (
        "Append a new task to the team's shared task list.  "
        "Use the returned task_id when calling TaskGet, TaskUpdate, or "
        "when wiring up blocked_by relationships between tasks."
    )
    params_model: type = TaskCreateParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TaskCreateParams)
                else TaskCreateParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TaskCreate args: {exc}", is_error=True)

        try:
            team = await self._team_manager.get(p.team)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to load team: {exc}", is_error=True)

        store = TaskStore(team.config_dir)
        try:
            task_id = await store.create(
                title=p.title,
                description=p.description,
                assignee=p.assignee,
                blocked_by=p.blocked_by,
            )
        except Exception as exc:
            return ToolResult(output=f"Failed to create task: {exc}", is_error=True)

        blocked_info = f" (blocked_by={','.join(p.blocked_by)})" if p.blocked_by else ""
        return ToolResult(
            output=f"OK — task '{p.title}' created (id={task_id}){blocked_info}."
        )