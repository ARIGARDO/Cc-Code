"""Tests for worktree session persistence."""

import tempfile
from pathlib import Path

import pytest

from cccode.worktree.session import (
    WorktreeSession,
    load_session,
    save_session,
    clear_session,
)


class TestWorktreeSession:
    def test_roundtrip(self) -> None:
        s = WorktreeSession(
            original_cwd="/tmp/project",
            worktree_path="/tmp/test",
            worktree_name="alice",
            original_branch="main",
            original_head_commit="abc123",
            session_id="session-1",
        )
        assert s.worktree_name == "alice"
        assert s.worktree_path == "/tmp/test"
        assert s.original_branch == "main"
        assert s.session_id == "session-1"

    def test_dict_roundtrip(self) -> None:
        s = WorktreeSession(
            original_cwd="/tmp/project",
            worktree_path="/tmp/test",
            worktree_name="alice",
            original_branch="main",
            original_head_commit="abc123",
            session_id="session-1",
        )
        d = s.to_dict()
        s2 = WorktreeSession.from_json(s.to_json())
        assert s2.to_dict() == d


class TestSessionPersistence:
    def test_save_and_load(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            s = WorktreeSession(
                original_cwd="/tmp/project",
                worktree_path="/tmp/test",
                worktree_name="alice",
                original_branch="main",
                original_head_commit="abc123",
                session_id="session-2",
            )
            save_session(path, s)

            loaded = load_session(path)
            assert loaded is not None
            assert loaded.worktree_name == "alice"
            assert loaded.session_id == "session-2"
        finally:
            path.unlink(missing_ok=True)

    def test_load_none(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("null")
            path = Path(f.name)

        try:
            loaded = load_session(path)
            assert loaded is None
        finally:
            path.unlink(missing_ok=True)

    def test_load_missing(self) -> None:
        loaded = load_session(Path("/nonexistent/path.json"))
        assert loaded is None

    def test_clear(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            s = WorktreeSession(
                original_cwd="/tmp/project",
                worktree_path="/tmp/test",
                worktree_name="alice",
                original_branch="main",
                original_head_commit="abc123",
                session_id="session-1",
            )
            save_session(path, s)
            clear_session(path)
            loaded = load_session(path)
            assert loaded is None
        finally:
            path.unlink(missing_ok=True)

    def test_corrupt_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = Path(f.name)

        try:
            with pytest.raises(ValueError):
                load_session(path)
        finally:
            path.unlink(missing_ok=True)