"""cccode.worktree — Git Worktree isolation management."""

from cccode.worktree.slug import validate_slug, flat_slug
from cccode.worktree.session import WorktreeSession, load_session, save_session, clear_session
from cccode.worktree.git import _run_git, _has_worktree_changes, _resolve_head_sha_from_fs
from cccode.worktree.manager import Manager, Worktree, DEFAULT_SYMLINK_DIRS
from cccode.worktree.create import create_worktree, _perform_post_creation_setup
from cccode.worktree.lifecycle import (
    ExitAction,
    ExitOptions,
    ExitReport,
    AutoCleanupReport,
    WorktreeHasChangesError,
    enter_worktree,
    exit_worktree,
    remove_worktree,
    auto_cleanup,
)
from cccode.worktree.sweep import sweep_stale, EPHEMERAL_PATTERN, random_agent_name

__all__ = [
    "AutoCleanupReport",
    "DEFAULT_SYMLINK_DIRS",
    "EPHEMERAL_PATTERN",
    "ExitAction",
    "ExitOptions",
    "ExitReport",
    "Manager",
    "Worktree",
    "WorktreeHasChangesError",
    "WorktreeSession",
    "auto_cleanup",
    "clear_session",
    "create_worktree",
    "enter_worktree",
    "exit_worktree",
    "flat_slug",
    "load_session",
    "random_agent_name",
    "remove_worktree",
    "save_session",
    "sweep_stale",
    "validate_slug",
    "_has_worktree_changes",
    "_perform_post_creation_setup",
    "_resolve_head_sha_from_fs",
    "_run_git",
]