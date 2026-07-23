"""TaskManager: background task lifecycle and notification queue."""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ProgressInfo:
    message: str = ""
    percentage: float = 0.0


@dataclass
class BackgroundTask:
    task_id: str = ""
    agent_type: str = ""
    status: str = "running"
    result: str = ""
    start_time: str = ""
    end_time: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    progress: ProgressInfo = field(default_factory=ProgressInfo)
    _async_task: asyncio.Task | None = field(default=None, repr=False)


class TaskManager:
    """Manage background sub-agent tasks with asyncio."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}
        self._notify_queue: asyncio.Queue[str] = asyncio.Queue()

    def launch(
        self,
        coro: Coroutine[Any, Any, str],
        agent_type: str = "",
    ) -> str:
        """Launch a background task and return its task ID."""
        task_id = uuid.uuid4().hex[:8]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bt = BackgroundTask(
            task_id=task_id,
            agent_type=agent_type,
            status="running",
            start_time=now,
        )
        self._tasks[task_id] = bt

        async_task = asyncio.create_task(
            self._run_background(task_id, coro)
        )
        self._async_tasks[task_id] = async_task
        bt._async_task = async_task

        return task_id

    async def _run_background(
        self,
        task_id: str,
        coro: Coroutine[Any, Any, str],
    ) -> None:
        """Run a coroutine as a background task, update state on completion."""
        bt = self._tasks.get(task_id)
        if bt is None:
            return
        try:
            result = await coro
            bt.status = "completed"
            bt.result = result
        except asyncio.CancelledError:
            bt.status = "cancelled"
            bt.result = "Task was cancelled"
        except Exception as e:
            bt.status = "failed"
            bt.result = str(e)
            logger.warning("Background task %s failed: %s", task_id, e)
        finally:
            bt.end_time = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
            await self._notify_queue.put(task_id)

    def adopt_running(
        self,
        agent: Any,
        agent_type: str = "",
        partial_result: str = "",
    ) -> str:
        """Adopt a currently running Agent instance as a background task."""
        task_id = uuid.uuid4().hex[:8]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bt = BackgroundTask(
            task_id=task_id,
            agent_type=agent_type,
            status="running",
            start_time=now,
            result=partial_result,
        )
        self._tasks[task_id] = bt

        async def _continue() -> str:
            if hasattr(agent, "run_to_completion"):
                remaining = await agent.run_to_completion("")
                return (partial_result + "\n" + remaining).strip()
            return partial_result

        async_task = asyncio.create_task(
            self._run_background(task_id, _continue())
        )
        self._async_tasks[task_id] = async_task
        bt._async_task = async_task

        return task_id

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        return list(self._tasks.values())

    async def cancel(self, task_id: str) -> bool:
        bt = self._tasks.get(task_id)
        if bt is None or bt.status != "running":
            return False
        at = self._async_tasks.get(task_id)
        if at and not at.done():
            at.cancel()
        bt.status = "cancelled"
        bt.end_time = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        return True

    def poll_completed(self) -> list[str]:
        """Non-blocking drain of the notification queue."""
        completed: list[str] = []
        while True:
            try:
                task_id = self._notify_queue.get_nowait()
                completed.append(task_id)
            except asyncio.QueueEmpty:
                break
        return completed