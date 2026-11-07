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
            slug="alice",
            flat_slug="alice",
            worktree_path="/tmp/test",
            branch="worktree-alice",
            serial=1,
        )
        assert s.slug == "alice"
        assert s.flat_slug == "alice"
        assert s.worktree_path == "/tmp/test"
        assert s.branch == "worktree-alice"
        assert s.serial == 1

    def test_dict_roundtrip(self) -> None:
        s = WorktreeSession(
            slug="alice",
            flat_slug="alice",
            worktree_path="/tmp/test",
            branch="worktree-alice",
            serial=1,
        )
        d = s.to_dict()
        s2 = WorktreeSession.from_dict(d)
        assert s2.slug == s.slug
        assert s2.flat_slug == s.flat_slug
        assert s2.worktree_path == s.worktree_path
        assert s2.branch == s.branch
        assert s2.serial == s.serial


class TestSessionPersistence:
    def test_save_and_load(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            s = WorktreeSession(
                slug="alice",
                flat_slug="alice",
                worktree_path="/tmp/test",
                branch="worktree-alice",
                serial=2,
            )
            save_session(path, s)

            loaded = load_session(path)
            assert loaded is not None
            assert loaded.slug == "alice"
            assert loaded.serial == 2
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
                slug="alice",
                flat_slug="alice",
                worktree_path="/tmp/test",
                branch="worktree-alice",
                serial=1,
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