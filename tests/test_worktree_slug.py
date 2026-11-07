"""Tests for worktree slug validation."""

import pytest

from cccode.worktree.slug import validate_slug, flat_slug


class TestValidateSlug:
    def test_valid_simple(self) -> None:
        validate_slug("alice")

    def test_valid_nested(self) -> None:
        validate_slug("team/alice")

    def test_valid_version(self) -> None:
        validate_slug("v1.0")

    def test_valid_underscore(self) -> None:
        validate_slug("a_b")

    def test_valid_dot(self) -> None:
        validate_slug("feature.branch")

    def test_valid_dash(self) -> None:
        validate_slug("feature-branch")

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            validate_slug("")

    def test_too_long(self) -> None:
        with pytest.raises(ValueError, match="长度不能超过"):
            validate_slug("a" * 65)

    def test_dot_segment(self) -> None:
        with pytest.raises(ValueError, match="段名不能是"):
            validate_slug(".")

    def test_dotdot_segment(self) -> None:
        with pytest.raises(ValueError, match="段名不能是"):
            validate_slug("..")

    def test_dotdot_path(self) -> None:
        with pytest.raises(ValueError, match="段名不能是"):
            validate_slug("../etc")

    def test_double_slash(self) -> None:
        with pytest.raises(ValueError, match="连续的"):
            validate_slug("a//b")

    def test_leading_slash(self) -> None:
        with pytest.raises(ValueError, match="不能以 '/' 开头"):
            validate_slug("/x")

    def test_trailing_slash(self) -> None:
        with pytest.raises(ValueError, match="不能以 '/' 结尾"):
            validate_slug("a/")

    def test_space(self) -> None:
        with pytest.raises(ValueError, match="非法字符"):
            validate_slug("a b")

    def test_semicolon(self) -> None:
        with pytest.raises(ValueError, match="非法字符"):
            validate_slug("a;b")

    def test_at_boundary(self) -> None:
        validate_slug("a" * 64)


class TestFlatSlug:
    def test_simple(self) -> None:
        assert flat_slug("alice") == "alice"

    def test_nested(self) -> None:
        assert flat_slug("team/alice") == "team+alice"

    def test_no_slash(self) -> None:
        assert flat_slug("feature-branch") == "feature-branch"