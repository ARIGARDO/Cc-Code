"""Worktree Manager — core class holding worktree state and dispatching to lifecycle/create/sweep."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mewcode.worktree.session import load_session, save_session, WorktreeSession
from mewcode.worktree.git import _resolve_head_sha_from_fs
from mewcode.worktree.lifecycle import (
    ExitAction,
    ExitOptions,
    ExitReport,
    AutoCleanupReport,
    enter_worktree,
    exit_worktree,
    remove_worktree,
    auto_cleanup,
)
from mewcode.worktree.create import create_worktree
from mewcode.worktree.sweep import sweep_stale

DEFAULT_SYMLINK_DIRS = ["node_modules", ".venv", "vendor"]


@dataclass
class Worktree:
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime
    manual: bool = False


class Manager:
    """Manages Git Worktree lifecycle for agent isolation."""

    def __init__(self, repo_root: str) -> None:
        import subprocess

        self.repo_root = str(Path(repo_root).resolve())
        result = subprocess.run(
            ["git", "-C", self.repo_root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        expected = str(Path(self.repo_root).resolve())
        actual = result.stdout.strip()
        if result.returncode != 0 or Path(actual).resolve() != Path(expected).resolve():
            raise ValueError(f"不是有效的 git 仓库根目录: {self.repo_root}")

        self.worktree_dir = Path(self.repo_root) / ".mewcode" / "worktrees"
        self.session_file = Path(self.repo_root) / ".mewcode" / "worktree_session.json"
        self.symlink_dirs = list(DEFAULT_SYMLINK_DIRS)
        self.lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self.current_session: WorktreeSession | None = None

        self.worktree_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.current_session = load_session(self.session_file)
        except ValueError:
            print(f"worktree: session 文件损坏,已清空", file=sys.stderr)
            self.current_session = None

        if self.current_session is not None:
            session_path = Path(self.current_session.worktree_path)
            if not session_path.exists():
                print(f"worktree: session 指向的 worktree 目录已不存在,已清空 session", file=sys.stderr)
                self.current_session = None
                save_session(self.session_file, None)

        self._scan_active()

    def _scan_active(self) -> None:
        """Scan worktree_dir for existing worktrees (fast recovery path)."""
        if not self.worktree_dir.exists():
            return
        for entry in self.worktree_dir.iterdir():
            if not entry.is_dir():
                continue
            name = self._name_from_dir(entry.name)
            if name is None:
                continue
            sha = _resolve_head_sha_from_fs(str(entry))
            branch = f"worktree-{entry.name}"
            wt = Worktree(
                name=name,
                path=str(entry),
                branch=branch,
                based_on="HEAD",
                head_commit=sha or "",
                created=datetime.fromtimestamp(entry.stat().st_mtime),
                manual=False,
            )
            self.active[name] = wt

    @staticmethod
    def _name_from_dir(dirname: str) -> str | None:
        """Reverse flat_slug: replace + back to /."""
        return dirname.replace("+", "/")

    def list(self) -> list[Worktree]:
        return sorted(self.active.values(), key=lambda w: w.name)

    def get(self, name: str) -> Worktree | None:
        return self.active.get(name)

    def get_current_session(self) -> WorktreeSession | None:
        return self.current_session

    async def create(self, name: str, base_ref: str = "HEAD", manual: bool = False) -> Worktree:
        return await create_worktree(self, name, base_ref, manual)

    async def enter(self, name: str) -> WorktreeSession:
        return await enter_worktree(self, name)

    async def exit(self, name: str, action: ExitAction, opts: ExitOptions | None = None) -> ExitReport:
        if opts is None:
            opts = ExitOptions()
        return await exit_worktree(self, name, action, opts)

    async def remove(self, name: str, opts: ExitOptions | None = None) -> None:
        if opts is None:
            opts = ExitOptions()
        await remove_worktree(self, name, opts)

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        return await auto_cleanup(self, name)

    async def sweep_stale(self, cutoff: datetime) -> list[str]:
        return await sweep_stale(self, cutoff)