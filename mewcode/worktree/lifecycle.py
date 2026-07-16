"""Worktree lifecycle — enter, exit, remove, auto_cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from mewcode.worktree.session import WorktreeSession, save_session
from mewcode.worktree.git import _run_git, _has_worktree_changes

if TYPE_CHECKING:
    from mewcode.worktree.manager import Manager


class ExitAction(str, Enum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass
class ExitOptions:
    discard_changes: bool = False


@dataclass
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(Exception):
    """Worktree 有未提交修改或本地多于 base 的 commit。"""


async def enter_worktree(manager: "Manager", name: str) -> WorktreeSession:
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        original_cwd = str(Path.cwd())
        try:
            original_branch = await _run_git(manager.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        except RuntimeError:
            original_branch = ""
        try:
            original_head = await _run_git(manager.repo_root, "rev-parse", "HEAD")
        except RuntimeError:
            original_head = ""

        session = WorktreeSession(
            original_cwd=original_cwd,
            worktree_path=wt.path,
            worktree_name=name,
            original_branch=original_branch,
            original_head_commit=original_head,
            session_id=secrets.token_hex(8),
        )

        manager.current_session = session
        save_session(manager.session_file, session)
        return session


async def exit_worktree(
    manager: "Manager",
    name: str,
    action: ExitAction,
    opts: ExitOptions,
) -> ExitReport:
    async with manager.lock:
        if manager.current_session is None:
            raise ValueError("没有活跃的 worktree session")
        if manager.current_session.worktree_name != name:
            raise ValueError(f"只能退出当前 session 的 worktree '{manager.current_session.worktree_name}',不是 '{name}'")

        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        if action == ExitAction.REMOVE and not opts.discard_changes:
            if await _has_worktree_changes(wt.path, wt.head_commit):
                raise WorktreeHasChangesError(
                    f"worktree '{name}' 有未提交的修改,使用 --discard 强制删除"
                )

        with contextlib.suppress(OSError):
            os.chdir(manager.current_session.original_cwd)

        manager.current_session = None
        save_session(manager.session_file, None)

        removed = False
        if action == ExitAction.REMOVE:
            removed = True
            await _run_git(manager.repo_root, "worktree", "remove", "--force", wt.path)
            await asyncio.sleep(0.1)
            try:
                await _run_git(manager.repo_root, "branch", "-D", wt.branch)
            except RuntimeError:
                pass
            manager.active.pop(name, None)

        return ExitReport(removed=removed, path=wt.path, branch=wt.branch)


async def remove_worktree(manager: "Manager", name: str, opts: ExitOptions) -> None:
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        if not opts.discard_changes:
            if await _has_worktree_changes(wt.path, wt.head_commit):
                raise WorktreeHasChangesError(
                    f"worktree '{name}' 有未提交的修改,使用 --discard 强制删除"
                )

        if manager.current_session is not None and manager.current_session.worktree_name == name:
            manager.current_session = None
            save_session(manager.session_file, None)

        await _run_git(manager.repo_root, "worktree", "remove", "--force", wt.path)
        await asyncio.sleep(0.1)
        try:
            await _run_git(manager.repo_root, "branch", "-D", wt.branch)
        except RuntimeError:
            pass
        manager.active.pop(name, None)


async def auto_cleanup(manager: "Manager", name: str) -> AutoCleanupReport:
    wt = manager.active.get(name)
    if wt is None:
        return AutoCleanupReport(kept=False)

    if wt.manual:
        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)

    if await _has_worktree_changes(wt.path, wt.head_commit):
        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)

    await remove_worktree(manager, name, ExitOptions(discard_changes=True))
    return AutoCleanupReport(kept=False)