"""Minimal file-content cache for the tool system.

ReadFile / WriteFile / EditFile consult this cache to avoid redundant I/O
during a single agent turn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class FileCache:
    """Simple in-memory cache mapping absolute path → (content, mtime)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    def get(self, path: Path) -> Optional[str]:
        key = str(path.resolve())
        entry = self._store.get(key)
        if entry is None:
            return None
        content, cached_mtime = entry
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return None
        if current_mtime != cached_mtime:
            del self._store[key]
            return None
        return content

    def set(self, path: Path, content: str) -> None:
        key = str(path.resolve())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        self._store[key] = (content, mtime)

    def invalidate(self, path: Path) -> None:
        key = str(path.resolve())
        self._store.pop(key, None)
