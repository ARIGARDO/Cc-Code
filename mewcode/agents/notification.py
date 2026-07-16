"""Task notification formatting and injection."""

from __future__ import annotations

import logging

from mewcode.agents.task_manager import BackgroundTask
from mewcode.conversation import ConversationManager

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_RESULT_LENGTH = 5000


def format_task_notification(task: BackgroundTask) -> str:
    """Format a completed task as a <task-notification> block."""
    result = task.result or ""
    if len(result) > MAX_NOTIFICATION_RESULT_LENGTH:
        result = result[:MAX_NOTIFICATION_RESULT_LENGTH] + "...\n... (truncated)"

    elapsed = ""
    if task.start_time and task.end_time:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(task.start_time)
            end = datetime.fromisoformat(task.end_time)
            elapsed = f"{(end - start).total_seconds():.1f}s"
        except Exception:
            elapsed = "unknown"

    tokens = ""
    if task.input_tokens or task.output_tokens:
        tokens = f"{task.input_tokens}in/{task.output_tokens}out"

    lines = [
        "<task-notification>",
        f"Task ID: {task.task_id}",
        f"Agent: {task.agent_type}",
        f"Status: {task.status}",
    ]
    if elapsed:
        lines.append(f"Elapsed: {elapsed}")
    if tokens:
        lines.append(f"Tokens: {tokens}")
    lines.append(f"Result:\n{result}")
    lines.append("</task-notification>")

    return "\n".join(lines)


def inject_task_notifications(
    conversation: ConversationManager,
    completed: list[BackgroundTask],
) -> None:
    """Inject completed task notifications into the conversation."""
    for task in completed:
        notification = format_task_notification(task)
        conversation.add_user_message(notification)