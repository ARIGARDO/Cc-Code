"""WorktreeSession persistence — JSON atomic write/read."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: str) -> "WorktreeSession":
        data = json.loads(raw)
        return cls(**data)


def load_session(path: Path) -> WorktreeSession | None:
    """Load a session from a JSON file. Returns None if missing/empty/null."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw or raw == "null":
        return None
    try:
        return WorktreeSession.from_json(raw)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(f"worktree session 文件损坏: {path}")


def save_session(path: Path, session: WorktreeSession | None) -> None:
    """Atomically write session JSON. ``None`` writes ``null``."""
    if session is None:
        content = "null"
    else:
        content = session.to_json()

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def clear_session(path: Path) -> None:
    """Clear the session file (write null)."""
    save_session(path, None)