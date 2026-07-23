"""Task store for cross-agent task sharing (TeamManager backend)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


VALID_STATUSES = {"pending", "in_progress", "completed", "blocked"}

STATUS_ICONS = {
    "pending": "○",
    "in_progress": "◐",
    "completed": "●",
    "blocked": "✕",
}


@dataclass
class Task:
    """A single task in the shared task board."""
    id: str
    title: str
    description: str = ""
    status: str = "pending"
    assignee: str = ""
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


class TaskStore:
    """In-memory task store for a single team."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._id_counter = 0

    def create(self, title: str, description: str = "", blocks: Optional[list[str]] = None, blocked_by: Optional[list[str]] = None) -> Task:
        self._id_counter += 1
        task = Task(
            id=f"task_{self._id_counter}",
            title=title,
            description=description,
            blocks=list(blocks) if blocks else [],
            blocked_by=list(blocked_by) if blocked_by else [],
        )
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def update(self, task_id: str, **kwargs: Any) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                if key == "status" and value not in VALID_STATUSES:
                    continue
                setattr(task, key, value)
        return task


class TeamManager:
    """Manages task stores for multiple teams."""

    def __init__(self) -> None:
        self._stores: dict[str, TaskStore] = {}

    def get_task_store(self, team_name: str) -> TaskStore:
        if team_name not in self._stores:
            self._stores[team_name] = TaskStore()
        return self._stores[team_name]

    def mailbox(self) -> "Mailbox":
        return Mailbox()


class Mailbox:
    """Simple mailbox for team messages."""

    def __init__(self) -> None:
        self._messages: list[str] = []

    def drain(self) -> list[str]:
        result = self._messages[:]
        self._messages.clear()
        return result