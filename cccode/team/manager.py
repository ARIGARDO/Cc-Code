"""TeamManager — in-memory cache backed by on-disk <home>/.cccode/teams/*.json."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from cccode.team.backend import detect_backend
from cccode.team.filelock import acquire_lock
from cccode.team.types import (
    BackendType,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamError,
    TeamExistsError,
    TeamHasActiveMembersError,
    TeamNotFoundError,
    TeammateInfo,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  helpers
# ──────────────────────────────────────────────

_SANITIZE_RE = re.compile(r"[^a-z0-9_-]+", flags=re.IGNORECASE)


def sanitize(name: str) -> str:
    """Turn a free-form team name into a safe path slug."""

    if not name or not name.strip():
        raise TeamError("Team name cannot be empty.")
    slug = _SANITIZE_RE.sub("-", name).strip("-").lower()
    if not slug:
        raise TeamError(f"Team name {name!r} produced an empty slug.")
    # Trim for filesystem safety
    return slug[:64]


# ──────────────────────────────────────────────
#  TeamManager
# ──────────────────────────────────────────────

class TeamManager:
    """Coordinate team creation / deletion / member management.

    The on-disk layout::

        <home_dir>/.cccode/teams/<slug>/config.json    # team + members
        <home_dir>/.cccode/teams/<slug>/tasks.json     # shared tasks
        <home_dir>/.cccode/teams/<slug>/mailbox/*.json # per-agent messages
        <home_dir>/.cccode/teams/<slug>/*.lock         # file locks

    A single ``asyncio.Lock`` protects the in-memory cache of team
    objects.  Filesystem-level locks protect against cross-process
    concurrency (tmux / iterm2 sub-processes that share the same team
    directory).
    """

    def __init__(self, home_dir: str) -> None:
        self.home_dir = str(home_dir)
        self._teams: dict[str, Team] = {}
        self._lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._root = Path(self.home_dir) / ".cccode" / "teams"
        self._root.mkdir(parents=True, exist_ok=True)

    # ── queries ───────────────────────────────
    def is_initialised(self) -> bool:
        return True

    def team_dir_for(self, sanitized_name: str) -> str:
        return str(self._root / sanitized_name)

    async def has(self, sanitized_name: str) -> bool:
        with self._thread_lock:
            if sanitized_name in self._teams:
                return True
        return (self._root / sanitized_name / "config.json").exists()

    async def list_(self) -> list[dict[str, Any]]:
        """Return a list of team summaries (name, sanitized_name, description)."""

        result: list[dict[str, Any]] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            cfg = child / "config.json"
            if not cfg.exists():
                continue
            try:
                raw = json.loads(cfg.read_text())
                if isinstance(raw, dict):
                    result.append({
                        "name": raw.get("name", child.name),
                        "sanitized_name": raw.get("sanitized_name", child.name),
                        "description": raw.get("description", ""),
                    })
            except Exception:
                pass
        return result

    # ── create/delete ─────────────────────────
    async def create(self, name: str, description: str = "") -> Team:
        sanitized = sanitize(name)

        async with self._lock:
            # Reload from disk to defeat race with other processes
            await self._reload_from_disk_locked()

            # In-memory conflict
            while sanitized in self._teams:
                sanitized = f"{sanitized}-2"
            # On-disk conflict (directory exists)
            while (self._root / sanitized).is_dir():
                sanitized = f"{sanitized}-2"

            config_dir = self._root / sanitized
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "mailbox").mkdir(exist_ok=True)

            backend = detect_backend(self.home_dir)

            team = Team(
                name=name,
                sanitized_name=sanitized,
                lead_agent_id="lead",
                backend=backend,
                description=description,
                config_dir=str(config_dir),
                config_path=str(config_dir / "config.json"),
                tasks_path=str(config_dir / "tasks.json"),
                mailbox_dir=str(config_dir / "mailbox"),
            )
            team.members.append(TeammateInfo(name="lead", agent_id="lead"))

            await self._save_team_locked(team)
            self._teams[sanitized] = team
            logger.info("[team] created team '%s' (%s)", name, sanitized)
            return team

    async def get(self, sanitized_name: str) -> Team:
        async with self._lock:
            team = self._teams.get(sanitized_name)
            if team is None:
                path = self._root / sanitized_name / "config.json"
                if not path.exists():
                    raise TeamNotFoundError(
                        f"Team '{sanitized_name}' not found"
                    )
                team = _load_team_from_path(
                    str(path), self._root, sanitized_name
                )
                self._teams[sanitized_name] = team
            else:
                # Always reload from disk to stay consistent with
                # teammates running in separate processes
                path = self._root / sanitized_name / "config.json"
                if path.exists():
                    team = _load_team_from_path(
                        str(path), self._root, sanitized_name
                    )
                    self._teams[sanitized_name] = team
            return team

    async def delete(self, sanitized_name: str, force: bool = False) -> None:
        async with self._lock:
            path = self._root / sanitized_name / "config.json"
            if not path.exists():
                # Already gone — treat as success
                self._teams.pop(sanitized_name, None)
                return

            team = _load_team_from_path(str(path), self._root, sanitized_name)
            if not force and team.has_active_members():
                raise TeamHasActiveMembersError(
                    f"Team '{sanitized_name}' has {team.active_count()} "
                    "active member(s); pass force=True to delete anyway."
                )
            # Remove directory
            try:
                shutil.rmtree(self._root / sanitized_name)
            except FileNotFoundError:
                pass
            self._teams.pop(sanitized_name, None)
            logger.info("[team] deleted team '%s'", sanitized_name)

    # ── member management ─────────────────────
    async def add_member(self, sanitized_name: str, info: TeammateInfo) -> None:
        async with self._lock:
            await self._reload_from_disk_locked()

            team = self._teams.get(sanitized_name)
            if team is None:
                path = self._root / sanitized_name / "config.json"
                if not path.exists():
                    raise TeamNotFoundError(
                        f"Team '{sanitized_name}' not found"
                    )
                team = _load_team_from_path(
                    str(path), self._root, sanitized_name
                )
                self._teams[sanitized_name] = team

            if team.member_by_name(info.name):
                raise MemberExistsError(
                    f"Member '{info.name}' already exists in team '{sanitized_name}'"
                )
            if not info.started_at:
                info.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            team.members.append(info)
            await self._save_team_locked(team)
            logger.info(
                "[team] member '%s' added to '%s' (agent=%s)",
                info.name, sanitized_name, info.agent_id or "-",
            )

    async def set_member_active(
        self, sanitized_name: str, member_name: str, is_active: bool
    ) -> None:
        async with self._lock:
            await self._reload_from_disk_locked()

            team = self._teams.get(sanitized_name)
            if team is None:
                path = self._root / sanitized_name / "config.json"
                if not path.exists():
                    raise TeamNotFoundError(
                        f"Team '{sanitized_name}' not found"
                    )
                team = _load_team_from_path(
                    str(path), self._root, sanitized_name
                )
                self._teams[sanitized_name] = team

            member = team.member_by_name(member_name)
            if member is None:
                raise MemberNotFoundError(
                    f"Member '{member_name}' not found in team '{sanitized_name}'"
                )
            member.is_active = is_active
            await self._save_team_locked(team)
            logger.info(
                "[team] member '%s' in '%s' now active=%s",
                member_name, sanitized_name, is_active,
            )

    async def update_member(
        self,
        sanitized_name: str,
        member_name: str,
        *,
        agent_id: str | None = None,
        pane_id: str | None = None,
        backend_type: str | None = None,
        worktree_path: str | None = None,
        session_dir: str | None = None,
    ) -> None:
        async with self._lock:
            await self._reload_from_disk_locked()

            team = self._teams.get(sanitized_name)
            if team is None:
                path = self._root / sanitized_name / "config.json"
                if not path.exists():
                    raise TeamNotFoundError(
                        f"Team '{sanitized_name}' not found"
                    )
                team = _load_team_from_path(
                    str(path), self._root, sanitized_name
                )
                self._teams[sanitized_name] = team

            member = team.member_by_name(member_name)
            if member is None:
                raise MemberNotFoundError(
                    f"Member '{member_name}' not found in team '{sanitized_name}'"
                )
            if agent_id is not None:
                member.agent_id = agent_id
            if pane_id is not None:
                member.pane_id = pane_id
            if backend_type is not None:
                member.backend_type = backend_type
            if worktree_path is not None:
                member.worktree_path = worktree_path
            if session_dir is not None:
                member.session_dir = session_dir
            await self._save_team_locked(team)

    async def remove_member(self, sanitized_name: str, member_name: str) -> None:
        async with self._lock:
            await self._reload_from_disk_locked()

            team = self._teams.get(sanitized_name)
            if team is None:
                path = self._root / sanitized_name / "config.json"
                if not path.exists():
                    raise TeamNotFoundError(
                        f"Team '{sanitized_name}' not found"
                    )
                team = _load_team_from_path(
                    str(path), self._root, sanitized_name
                )
                self._teams[sanitized_name] = team

            if not team.member_by_name(member_name):
                raise MemberNotFoundError(
                    f"Member '{member_name}' not found in team '{sanitized_name}'"
                )
            team.members = [m for m in team.members if m.name != member_name]
            await self._save_team_locked(team)

    async def get_members(self, sanitized_name: str) -> list[TeammateInfo]:
        team = await self.get(sanitized_name)
        return list(team.members)

    # ── internal helpers ──────────────────────
    async def _reload_from_disk_locked(self) -> None:
        """Reload every team we have cached from disk.

        Called *before* any mutation so cross-process updates are not
        silently lost.  Only updates teams whose config files still exist.
        """

        present: list[str] = []
        for name, _ in list(self._teams.items()):
            path = self._root / name / "config.json"
            if path.exists():
                try:
                    self._teams[name] = _load_team_from_path(
                        str(path), self._root, name
                    )
                    present.append(name)
                except Exception:
                    logger.exception("[team] failed to reload team %s", name)

    async def _save_team_locked(self, team: Team) -> None:
        """Atomically write ``team`` to ``config.json`` (with file lock)."""

        lock_path = str(Path(team.config_dir) / "config.lock")
        async with acquire_lock(lock_path):
            data = team.to_dict()
            path = Path(team.config_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(path)


# ──────────────────────────────────────────────
#  module-level helpers
# ──────────────────────────────────────────────

def _load_team_from_path(
    config_path: str, root: Path, sanitized_name: str
) -> Team:
    raw = json.loads(Path(config_path).read_text())
    team = Team.from_dict(raw)
    config_dir = str(root / sanitized_name)
    team.config_dir = config_dir
    team.config_path = str(root / sanitized_name / "config.json")
    team.tasks_path = str(root / sanitized_name / "tasks.json")
    team.mailbox_dir = str(root / sanitized_name / "mailbox")
    return team