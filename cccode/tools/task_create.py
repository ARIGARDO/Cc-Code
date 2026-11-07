"""TaskCreate — create a new task on the shared task board."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cccode.tools.base import Tool, ToolResult
from cccode.task_store import TeamManager


class TaskCreateParams(BaseModel):
    title: str = Field(description="Title of the task")
    description: str = Field(default="", description="Detailed description of the task")
    blocks: list[str] = Field(default_factory=list, description="Task IDs that this task blocks")
    blocked_by: list[str] = Field(default_factory=list, description="Task IDs that block this task")


class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = "Create a new task on the shared team task board. Use this to delegate work to other agents or track subtasks."
    params_model = TaskCreateParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, team_manager: TeamManager, team_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name

    async def execute(self, params: Any) -> ToolResult:
        store = self._team_manager.get_task_store(self._team_name)
        task = store.create(
            title=params.title,
            description=params.description,
            blocks=params.blocks,
            blocked_by=params.blocked_by,
        )
        return ToolResult(
            output=f"Created task {task.id}: {task.title} (status: {task.status})",
            is_error=False,
        )