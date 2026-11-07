"""Worktree sweep — background cleanup of stale temporary worktrees."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cccode.worktree.git import _run_git, _has_worktree_changes
from cccode.worktree.lifecycle import ExitOptions, remove_worktree

if TYPE_CHECKING:
    from cccode.worktree.manager import Manager

EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


def random_agent_name() -> str:
    """Generate a random temporary agent worktree name: ``agent-a<hex>``."""
    return "agent-a" + secrets.token_hex(4)[:7]


async def sweep_stale(manager: "Manager", cutoff: datetime) -> list[str]:
    """Sweep stale temporary worktrees.

    Three-layer filter:
    1. Name must match ``agent-a[0-9a-f]{7}``
    2. mtime must be before cutoff, skip current session
    3. No uncommitted changes, no unpushed commits
    """
    removed: list[str] = []
    if not manager.worktree_dir.exists():
        return removed

    for entry in manager.worktree_dir.iterdir():
        if not entry.is_dir():
            continue

        name = entry.name
        if not EPHEMERAL_PATTERN.match(name):
            continue

        mtime = datetime.fromtimestamp(entry.stat().st_mtime)
        if mtime > cutoff:
            continue

        if manager.current_session is not None:
            if str(manager.current_session.worktree_path) == str(entry):
                continue

        try:
            if await _has_worktree_changes(str(entry), "HEAD"):
                continue
        except RuntimeError:
            continue

        try:
            result = await _run_git(str(entry), "rev-list", "--max-count=1", "HEAD", "--not", "--remotes")
            if result.strip():
                continue
        except RuntimeError:
            continue

        try:
            await remove_worktree(manager, name, ExitOptions(discard_changes=True))
            removed.append(name)
        except Exception:
            continue

    return removed