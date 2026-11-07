"""Tests for worktree context path resolution."""

from pathlib import Path

from cccode.tools.ctx import resolve_path, with_cwd, _ctx_cwd


class TestResolvePath:
    def test_absolute_path(self) -> None:
        assert resolve_path("/tmp") == "/tmp"

    def test_relative_no_cwd(self) -> None:
        cwd = str(Path.cwd())
        result = resolve_path("foo")
        assert result == str(Path(cwd) / "foo")

    def test_relative_with_cwd(self) -> None:
        with with_cwd("/tmp"):
            assert resolve_path("foo") == "/tmp/foo"

    def test_empty_no_cwd(self) -> None:
        cwd = str(Path.cwd())
        assert resolve_path("") == cwd

    def test_empty_with_cwd(self) -> None:
        with with_cwd("/tmp"):
            assert resolve_path("") == "/tmp"

    def test_nested_cwd(self) -> None:
        with with_cwd("/tmp"):
            assert resolve_path("foo") == "/tmp/foo"
            with with_cwd("/var"):
                assert resolve_path("foo") == "/var/foo"
            assert resolve_path("foo") == "/tmp/foo"

    def test_cwd_restored_after_exception(self) -> None:
        old = _ctx_cwd.get()
        try:
            with with_cwd("/tmp"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert _ctx_cwd.get() == old

    def test_none_cwd(self) -> None:
        with with_cwd(None):
            assert resolve_path("foo") == str(Path.cwd() / "foo")