"""Git subprocess helpers — unified git command runner for worktree operations."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


def _git_env() -> dict[str, str]:
    """Return a copy of os.environ with Git prompt disabled."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    return env


async def _run_git(work_dir: str, *args: str) -> str:
    """Run a git command in *work_dir* and return stdout (stripped).

    Raises RuntimeError on failure.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=work_dir,
        env=_git_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        raise RuntimeError(stderr or f"git {' '.join(args)} failed with code {proc.returncode}")

    return stdout


async def _has_worktree_changes(wt_path: str, base_commit: str) -> bool:
    """Check if a worktree has uncommitted modifications or new commits beyond base.

    Fail-closed: any git error returns True (preserve worktree).
    """
    try:
        status = await _run_git(wt_path, "status", "--porcelain")
        if status.strip():
            return True
    except RuntimeError:
        return True

    try:
        count_str = await _run_git(wt_path, "rev-list", "--count", f"{base_commit}..HEAD")
        if count_str.isdigit() and int(count_str) > 0:
            return True
    except RuntimeError:
        return True

    return False


def _resolve_head_sha_from_fs(wt_path: str) -> str | None:
    """Resolve HEAD commit SHA from the filesystem only (no git subprocess).

    Reads the ``.git`` file (worktree pointer), then resolves HEAD -> ref -> SHA.
    Returns None on any failure.
    """
    try:
        git_file = Path(wt_path) / ".git"
        if not git_file.exists():
            return None

        git_content = git_file.read_text(encoding="utf-8").strip()
        if git_content.startswith("gitdir: "):
            git_dir = Path(git_content[8:].strip())
        else:
            git_dir = git_file

        head_file = git_dir / "HEAD"
        if not head_file.exists():
            return None

        head_content = head_file.read_text(encoding="utf-8").strip()
        if head_content.startswith("ref: "):
            ref_path = head_content[5:].strip()
            ref_file = git_dir / ref_path
            if ref_file.exists():
                return ref_file.read_text(encoding="utf-8").strip()
            return None
        else:
            return head_content

    except (OSError, UnicodeDecodeError):
        return None