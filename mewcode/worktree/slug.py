"""Worktree slug validation and flattening."""

from __future__ import annotations

import re

_MAX_SLUG_LENGTH = 64
_SLUG_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> None:
    """Validate a worktree slug name.

    Rules:
    - Non-empty, total length <= 64
    - Split by ``/``, each segment must match ``^[a-zA-Z0-9._-]+$``
    - No segment may be ``.`` or ``..``
    - No consecutive ``//``, no leading/trailing ``/``
    """
    if not name:
        raise ValueError("worktree slug 不能为空")
    if len(name) > _MAX_SLUG_LENGTH:
        raise ValueError(f"worktree slug 长度不能超过 {_MAX_SLUG_LENGTH} 字符")
    if name.startswith("/"):
        raise ValueError("worktree slug 不能以 '/' 开头")
    if name.endswith("/"):
        raise ValueError("worktree slug 不能以 '/' 结尾")
    if "//" in name:
        raise ValueError("worktree slug 不能包含连续的 '//'")

    segments = name.split("/")
    for seg in segments:
        if not seg:
            raise ValueError("worktree slug 包含空段")
        if seg == "." or seg == "..":
            raise ValueError(f"worktree slug 段名不能是 '{seg}'")
        if not _SLUG_SEGMENT_RE.match(seg):
            raise ValueError(f"worktree slug 段名 '{seg}' 包含非法字符,仅允许 [a-zA-Z0-9._-]")


def flat_slug(name: str) -> str:
    """Flatten a slug by replacing ``/`` with ``+`` to avoid Git D/F conflicts."""
    return name.replace("/", "+")