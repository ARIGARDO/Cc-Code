"""TaskGet — retrieve details of a specific task."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cccode.tools.base import Tool, ToolResult
from cccode.task_store import TeamManager


class TaskGetParams(BaseModel):
    task_id: str = Field(description="ID of the task to retrieve")


class TaskGetTool(Tool):
    name = "TaskGet"
    description = "Retrieve details of a specific task from the shared task board by its ID."
    params_model = TaskGetParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, team_manager: TeamManager, team_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name

    async def execute(self, params: Any) -> ToolResult:
        store = self._team_manager.get_task_store(self._team_name)
        task = store.get(params.task_id)
        if task is None:
            return ToolResult(
                output=f"Error: task {params.task_id} not found",
                is_error=True,
            )
        blocks_str = ", ".join(task.blocks) if task.blocks else "none"
        blocked_by_str = ", ".join(task.blocked_by) if task.blocked_by else "none"
        return ToolResult(
            output=(
                f"Task {task.id}: {task.title}\n"
                f"  Status: {task.status}\n"
                f"  Description: {task.description}\n"
                f"  Blocks: {blocks_str}\n"
                f"  Blocked by: {blocked_by_str}"
            ),
            is_error=False,
        )