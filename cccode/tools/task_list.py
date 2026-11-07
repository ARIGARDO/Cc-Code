"""TaskList — list all tasks on the shared task board."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from cccode.tools.base import Tool, ToolResult
from cccode.task_store import STATUS_ICONS, TeamManager


class TaskListParams(BaseModel):
    pass


class TaskListTool(Tool):
    name = "TaskList"
    description = "List all tasks on the shared team task board with their statuses."
    params_model = TaskListParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, team_manager: TeamManager, team_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name

    async def execute(self, params: Any) -> ToolResult:
        store = self._team_manager.get_task_store(self._team_name)
        tasks = store.list_tasks()
        if not tasks:
            return ToolResult(output="No tasks found.", is_error=False)
        lines = []
        for task in tasks:
            icon = STATUS_ICONS.get(task.status, "?")
            lines.append(f"  {icon} {task.id}: {task.title} [{task.status}]")
        return ToolResult(output="\n".join(lines), is_error=False)