"""Coordinator mode — restrict orchestrator to dispatch + read ops.

When coordinator mode is active, the lead agent's tool belt is reduced
to a small whitelist so that it cannot directly edit files or run
commands.  Its only channel for real work is the ``Agent`` tool, and it
is expected to rely on teammates for low-level changes.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  constants
# ──────────────────────────────────────────────

COORDINATOR_ALLOWED_TOOLS: list[str] = [
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "read_file",
    "glob",
    "grep",
    "bash",
]

# Tools we never want the coordinator to see
COORDINATOR_FORBIDDEN_TOOLS: list[str] = [
    "edit_file",
    "write_file",
    "write_file_tool",
]

ENV_COORDINATOR = "MEWCODE_COORDINATOR_MODE"


# ──────────────────────────────────────────────
#  public API
# ──────────────────────────────────────────────

def is_enabled(cfg: object | None = None) -> bool:
    """True when both the feature flag and the environment variable are set.

    The feature-flag argument is optional — when omitted we only check
    the environment variable.  When provided it is consulted via
    ``hasattr(cfg, 'feature_coordinator_mode')`` and must be truthy.
    """

    env_flag = os.environ.get(ENV_COORDINATOR, "").strip().lower()
    env_truthy = env_flag in {"1", "true", "yes", "on"}

    if cfg is not None:
        feature_flag = getattr(cfg, "feature_coordinator_mode", False) is True
        return bool(feature_flag and env_truthy)
    return bool(env_truthy)


def set_env_enabled(value: bool) -> None:
    """Toggle the coordinator-mode environment flag (same process only)."""

    if value:
        os.environ[ENV_COORDINATOR] = "1"
    else:
        os.environ.pop(ENV_COORDINATOR, None)


def system_prompt_suffix() -> str:
    """A short reminder paragraph to inject into the lead agent prompt."""

    return (
        "You are running in COORDINATOR mode.  Your job is to decompose "
        "work into tasks and delegate those tasks to teammate agents.  "
        "You may NOT directly modify files.  You may only use the "
        "following operations: TeamCreate / TeamDelete / TaskCreate / "
        "TaskGet / TaskList / TaskUpdate / SendMessage, plus read-only "
        "tools (read_file, glob, grep) and the Agent tool to spawn "
        "teammates.  After you dispatch a task, wait for the teammate to "
        "report back before moving forward — do not poll."
    )


def filter_tool_names(names: Iterable[str]) -> list[str]:
    """Return the subset of tool names a coordinator is allowed to use."""

    allowed = set(COORDINATOR_ALLOWED_TOOLS)
    forbidden = set(COORDINATOR_FORBIDDEN_TOOLS)
    result: list[str] = []
    for name in names:
        if name in forbidden:
            continue
        if name in allowed:
            result.append(name)
    return result


def should_keep_tool(tool_name: str) -> bool:
    """Convenience predicate used by tool registries."""

    if tool_name in COORDINATOR_FORBIDDEN_TOOLS:
        return False
    if tool_name in COORDINATOR_ALLOWED_TOOLS:
        return True
    return False