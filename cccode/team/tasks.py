"""Shared team task list with dependency graph support."""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

from cccode.team.filelock import acquire_lock
from cccode.team.types import TaskStatus, TeamTask


class TaskStore:
    """Persist and query a team's shared task list.

    On-disk layout::

        <config_dir>/tasks.json        {"tasks": [...]}
        <config_dir>/tasks.lock        lock file (O_CREAT|O_EXCL)

    All public calls go through the file lock so concurrent writers
    (in-process async tasks or external tmux sub-processes) do not
    corrupt the file.
    """

    def __init__(self, config_dir: str) -> None:
        self._dir = config_dir
        Path(self._dir).mkdir(parents=True, exist_ok=True)
        self._path = f"{self._dir}/tasks.json"
        self._lock_path = f"{self._dir}/tasks.lock"

    # ── CRUD ──────────────────────────────────

    async def create(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        blocked_by: list[str] | None = None,
    ) -> str:
        """Create a new task and return its ``task_<hex>`` id."""

        task_id = "task_" + secrets.token_hex(3)
        now = int(time.time())

        async with acquire_lock(self._lock_path):
            tasks = self._load()
            task = TeamTask(
                id=task_id,
                title=title,
                description=description,
                status=TaskStatus.PENDING,
                assignee=assignee,
                blocked_by=list(blocked_by or []),
                created_at=now,
                updated_at=now,
            )
            # Wire up reverse dependency on blocker tasks
            for blocker_id in task.blocked_by:
                for other in tasks:
                    if other.id == blocker_id:
                        if task_id not in other.blocks:
                            other.blocks.append(task_id)
                        other.updated_at = now
                        break
            tasks.append(task)
            self._save(tasks)
        return task_id

    async def get(self, task_id: str) -> TeamTask | None:
        async with acquire_lock(self._lock_path):
            for t in self._load():
                if t.id == task_id:
                    return t
        return None

    async def list_(
        self,
        status: str | None = None,
        assignee: str | None = None,
        include_ready: bool = True,
    ) -> list[TeamTask]:
        """Return tasks, optionally filtered, with ``is_ready`` field.

        ``is_ready`` is True when all entries in ``blocked_by`` point to
        completed tasks (a task with no blockers is trivially ready).
        """
        async with acquire_lock(self._lock_path):
            tasks = self._load()

            if status:
                tasks = [t for t in tasks if t.status == status]
            if assignee:
                tasks = [t for t in tasks if t.assignee == assignee]

            if include_ready:
                completed_ids = {
                    t.id for t in self._load() if t.status == TaskStatus.COMPLETED
                }
                for t in tasks:
                    t.is_ready = all(b in completed_ids for b in t.blocked_by)  # type: ignore[attr-defined]
            return tasks

    async def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        remove_blocks: list[str] | None = None,
        remove_blocked_by: list[str] | None = None,
    ) -> bool:
        """Modify a task; returns True if the task existed and was changed."""

        async with acquire_lock(self._lock_path):
            tasks = self._load()
            now = int(time.time())

            target = None
            for t in tasks:
                if t.id == task_id:
                    target = t
                    break

            if target is None:
                return False

            if title is not None:
                target.title = title
            if description is not None:
                target.description = description
            if status is not None:
                target.status = status
            if assignee is not None:
                target.assignee = assignee

            if add_blocked_by:
                for blocker_id in add_blocked_by:
                    if blocker_id not in target.blocked_by:
                        target.blocked_by.append(blocker_id)
                    # Wire up reverse edge on the blocker task
                    for other in tasks:
                        if other.id == blocker_id and task_id not in other.blocks:
                            other.blocks.append(task_id)
                            other.updated_at = now

            if remove_blocked_by:
                for blocker_id in remove_blocked_by:
                    if blocker_id in target.blocked_by:
                        target.blocked_by.remove(blocker_id)
                    for other in tasks:
                        if other.id == blocker_id and task_id in other.blocks:
                            other.blocks.remove(task_id)
                            other.updated_at = now

            if add_blocks:
                for downstream_id in add_blocks:
                    if downstream_id not in target.blocks:
                        target.blocks.append(downstream_id)
                    for other in tasks:
                        if other.id == downstream_id and task_id not in other.blocked_by:
                            other.blocked_by.append(task_id)
                            other.updated_at = now

            if remove_blocks:
                for downstream_id in remove_blocks:
                    if downstream_id in target.blocks:
                        target.blocks.remove(downstream_id)
                    for other in tasks:
                        if other.id == downstream_id and task_id in other.blocked_by:
                            other.blocked_by.remove(task_id)
                            other.updated_at = now

            target.updated_at = now
            self._save(tasks)
            return True

    async def delete(self, task_id: str) -> bool:
        async with acquire_lock(self._lock_path):
            tasks = self._load()
            remaining = [t for t in tasks if t.id != task_id]
            if len(remaining) == len(tasks):
                return False
            for t in remaining:
                t.blocked_by = [b for b in t.blocked_by if b != task_id]
                t.blocks = [b for b in t.blocks if b != task_id]
            self._save(remaining)
            return True

    # ── file I/O helpers ──────────────────────

    def _load(self) -> list[TeamTask]:
        path = Path(self._path)
        if not path.exists():
            return []
        try:
            import json as _json
            raw = _json.loads(path.read_text())
        except Exception:
            return []

        if not isinstance(raw, dict) or "tasks" not in raw:
            return []

        items = raw["tasks"]
        if not isinstance(items, list):
            return []
        return [TeamTask.from_dict(item) for item in items if isinstance(item, dict)]

    def _save(self, tasks: list[TeamTask]) -> None:
        import json as _json
        path = Path(self._path)
        data = {"tasks": [t.to_dict() for t in tasks]}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json.dumps(data, indent=2))
        tmp.replace(path)