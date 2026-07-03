"""System prompt builders and plan-mode reminders."""

from __future__ import annotations

from pathlib import Path

_REMINDER_INTERVAL = 5

_PLAN_MODE_FULL_REMINDER = """You are in Plan Mode. You may NOT use any write tools (WriteFile, EditFile, Bash) or any tool that modifies the system.

Instead, write your plan to the plan file using ReadFile / WriteFile. The plan file is at:
{plan_path}

When you are ready to execute the plan, exit Plan Mode with /do or ask the user to switch modes."""

_PLAN_MODE_SPARSE_REMINDER = "You are still in Plan Mode. No write tools allowed."


def build_system_prompt(
    coordinator_mode: bool = False,
    extra_instructions: str = "",
) -> str:
    """Build the system prompt string.

    If coordinator_mode is True, the system prompt is tailored for a coordinator agent.
    """
    if coordinator_mode:
        base = (
            "You are a coordinator agent. Your job is to break down tasks and delegate "
            "subtasks to other agents. Do not execute tools directly; instead, use the "
            "team task tools to create and manage work items."
        )
    else:
        base = (
            "You are MewCode, a terminal AI coding assistant. "
            "You have access to tools for reading, writing, editing files, "
            "executing shell commands, searching code, and more. "
            "Always use the right tool for the job. "
            "When reading files, prefer ReadFile over Bash cat. "
            "When searching, prefer Glob/Grep over Bash find/grep."
        )

    if extra_instructions:
        base = f"{base}\n\n{extra_instructions}"

    return base


def build_plan_mode_reminder(
    plan_path: Path,
    plan_exists: bool,
    iteration: int,
) -> str:
    """Build the plan mode reminder for the given iteration.

    - iteration == 1: full reminder
    - Every _REMINDER_INTERVAL iterations: full reminder
    - Other iterations: sparse reminder
    """
    if iteration == 1 or iteration % _REMINDER_INTERVAL == 0:
        return _PLAN_MODE_FULL_REMINDER.format(plan_path=str(plan_path))
    else:
        return _PLAN_MODE_SPARSE_REMINDER