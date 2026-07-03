"""TaskUpdate — update the status or details of a task."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult
from mewcode.task_store import VALID_STATUSES, TeamManager


class TaskUpdateParams(BaseModel):
    task_id: str = Field(description="ID of the task to update")
    status: Optional[str] = Field(default=None, description=f"New status: {', '.join(sorted(VALID_STATUSES))}")
    title: Optional[str] = Field(default=None, description="New title for the task")
    description: Optional[str] = Field(default=None, description="New description for the task")


class TaskUpdateTool(Tool):
    name = "TaskUpdate"
    description = f"Update the status or details of a task on the shared board. Valid statuses: {', '.join(sorted(VALID_STATUSES))}."
    params_model = TaskUpdateParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, team_manager: TeamManager, team_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name

    async def execute(self, params: Any) -> ToolResult:
        if params.status is not None and params.status not in VALID_STATUSES:
            return ToolResult(
                output=f"Error: invalid status '{params.status}'. Valid: {', '.join(sorted(VALID_STATUSES))}",
                is_error=True,
            )
        store = self._team_manager.get_task_store(self._team_name)
        updates: dict[str, Any] = {}
        if params.status is not None:
            updates["status"] = params.status
        if params.title is not None:
            updates["title"] = params.title
        if params.description is not None:
            updates["description"] = params.description
        if not updates:
            return ToolResult(output="No updates provided.", is_error=True)
        task = store.update(params.task_id, **updates)
        if task is None:
            return ToolResult(
                output=f"Error: task {params.task_id} not found",
                is_error=True,
            )
        return ToolResult(
            output=f"Updated task {task.id}: {task.title} (status: {task.status})",
            is_error=False,
        )