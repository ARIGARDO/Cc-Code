"""TaskUpdate tool — modify an existing task's fields."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mewcode.team.manager import TeamManager
from mewcode.team.tasks import TaskStore
from mewcode.team.types import TeamNotFoundError
from mewcode.tools.base import Tool, ToolResult


class TaskUpdateParams(BaseModel):
    team: str = Field(..., description="Sanitised team slug.")
    task_id: str = Field(..., description="The task_<hex> identifier.")
    title: str | None = Field(default=None, description="New title.")
    description: str | None = Field(default=None, description="New description.")
    status: str | None = Field(
        default=None,
        description="New status: pending | in_progress | completed | blocked.",
    )
    assignee: str | None = Field(default=None, description="New assignee.")
    add_blocks: list[str] | None = Field(
        default=None,
        description="Extra task_ids this task is a dependency for.",
    )
    add_blocked_by: list[str] | None = Field(
        default=None,
        description="Extra task_ids this task depends on.",
    )
    remove_blocks: list[str] | None = Field(
        default=None,
        description="task_ids to remove from the 'blocks' list.",
    )
    remove_blocked_by: list[str] | None = Field(
        default=None,
        description="task_ids to remove from the 'blocked_by' list.",
    )


class TaskUpdateTool(Tool):
    name: str = "TaskUpdate"
    description: str = (
        "Modify a task's title, description, status, assignee, or "
        "dependency edges.  Omitted fields are left unchanged."
    )
    params_model: type = TaskUpdateParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, TaskUpdateParams)
                else TaskUpdateParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid TaskUpdate args: {exc}", is_error=True)

        try:
            team = await self._team_manager.get(p.team)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to load team: {exc}", is_error=True)

        store = TaskStore(team.config_dir)
        try:
            changed = await store.update(
                task_id=p.task_id,
                title=p.title,
                description=p.description,
                status=p.status,
                assignee=p.assignee,
                add_blocks=p.add_blocks,
                add_blocked_by=p.add_blocked_by,
                remove_blocks=p.remove_blocks,
                remove_blocked_by=p.remove_blocked_by,
            )
        except Exception as exc:
            return ToolResult(output=f"Failed to update task: {exc}", is_error=True)

        if not changed:
            return ToolResult(
                output=f"Task '{p.task_id}' not found (no changes made).",
                is_error=True,
            )
        return ToolResult(output=f"OK — task '{p.task_id}' updated.")