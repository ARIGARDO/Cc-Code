"""Worktree creation — create, fast-recovery, post-creation setup steps."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mewcode.worktree.slug import validate_slug, flat_slug
from mewcode.worktree.git import _run_git, _resolve_head_sha_from_fs

if TYPE_CHECKING:
    from mewcode.worktree.manager import Manager, Worktree


async def create_worktree(
    manager: "Manager",
    name: str,
    base_ref: str = "HEAD",
    manual: bool = False,
) -> "Worktree":
    from mewcode.worktree.manager import Worktree

    validate_slug(name)

    async with manager.lock:
        if name in manager.active:
            raise ValueError(f"worktree '{name}' 已存在")

        flat = flat_slug(name)
        wt_path = manager.worktree_dir / flat
        branch = f"worktree-{flat}"

        if wt_path.exists():
            sha = _resolve_head_sha_from_fs(str(wt_path))
            wt = Worktree(
                name=name,
                path=str(wt_path),
                branch=branch,
                based_on=base_ref,
                head_commit=sha or "",
                created=datetime.fromtimestamp(wt_path.stat().st_mtime),
                manual=manual,
            )
            manager.active[name] = wt
            return wt

        try:
            await _run_git(
                manager.repo_root,
                "worktree", "add", "-B", branch,
                str(wt_path), base_ref,
            )
        except RuntimeError:
            shutil.rmtree(wt_path, ignore_errors=True)
            raise

        await _perform_post_creation_setup(manager.repo_root, str(wt_path), manager.symlink_dirs)

        head_sha = await _run_git(str(wt_path), "rev-parse", "HEAD")

        wt = Worktree(
            name=name,
            path=str(wt_path),
            branch=branch,
            based_on=base_ref,
            head_commit=head_sha,
            created=datetime.now(),
            manual=manual,
        )
        manager.active[name] = wt
        return wt


async def _perform_post_creation_setup(
    repo_root: str,
    wt_path: str,
    symlink_dirs: list[str],
) -> None:
    _copy_local_configs(repo_root, wt_path)
    await _setup_git_hooks(repo_root, wt_path)
    _symlink_large_dirs(repo_root, wt_path, symlink_dirs)
    await _copy_included_ignored(repo_root, wt_path)


def _copy_local_configs(repo_root: str, wt_path: str) -> None:
    config_files = [
        ".mewcode/config.yaml",
        ".mewcode/settings.local.yaml",
    ]
    for rel in config_files:
        src = Path(repo_root) / rel
        dst = Path(wt_path) / rel
        try:
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(str(src), str(dst))
        except Exception as e:
            print(f"worktree: setup copy_configs '{rel}': {e}", file=sys.stderr)


async def _setup_git_hooks(repo_root: str, wt_path: str) -> None:
    try:
        husky_dir = Path(repo_root) / ".husky"
        if husky_dir.is_dir():
            hooks_path = str(husky_dir.resolve())
            await _run_git(wt_path, "config", "core.hooksPath", hooks_path)
            return

        hooks_path = await _run_git(repo_root, "config", "--get", "core.hooksPath")
        if hooks_path.strip():
            await _run_git(wt_path, "config", "core.hooksPath", hooks_path.strip())
    except Exception as e:
        print(f"worktree: setup git_hooks: {e}", file=sys.stderr)


def _symlink_large_dirs(repo_root: str, wt_path: str, symlink_dirs: list[str]) -> None:
    for dir_name in symlink_dirs:
        src = Path(repo_root) / dir_name
        dst = Path(wt_path) / dir_name
        try:
            if src.exists() and not dst.exists():
                os.symlink(str(src), str(dst))
        except Exception as e:
            print(f"worktree: setup symlink '{dir_name}': {e}", file=sys.stderr)


async def _copy_included_ignored(repo_root: str, wt_path: str) -> None:
    include_file = Path(repo_root) / ".worktreeinclude"
    if not include_file.exists():
        return

    try:
        patterns = []
        for line in include_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
        if not patterns:
            return
    except Exception as e:
        print(f"worktree: setup include_ignored read: {e}", file=sys.stderr)
        return

    try:
        ignored_output = await _run_git(
            repo_root,
            "ls-files", "--others", "--ignored", "--exclude-standard", "--directory",
        )
    except RuntimeError as e:
        print(f"worktree: setup include_ignored ls-files: {e}", file=sys.stderr)
        return

    for line in ignored_output.splitlines():
        rel_path = line.strip()
        if not rel_path:
            continue
        if rel_path.endswith("/"):
            continue

        matched = False
        for pat in patterns:
            if fnmatch.fnmatch(rel_path, pat):
                matched = True
                break
        if not matched:
            continue

        src = Path(repo_root) / rel_path
        dst = Path(wt_path) / rel_path
        try:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(str(src), str(dst))
        except Exception as e:
            print(f"worktree: setup include_ignored copy '{rel_path}': {e}", file=sys.stderr)
            continue