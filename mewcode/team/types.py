"""ch15 Team — core data types."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ──────────────────────────────────────────────
#  Exceptions
# ──────────────────────────────────────────────

class TeamError(Exception):
    """Base class for all team-related errors."""


class TeamNotFoundError(TeamError):
    """Requested team does not exist."""


class TeamExistsError(TeamError):
    """Team with this name already exists."""


class TeamHasActiveMembersError(TeamError):
    """Team cannot be deleted because it has active members."""


class MemberNotFoundError(TeamError):
    """Named member does not exist in the team."""


class MemberExistsError(TeamError):
    """Member with this name already exists in the team."""


class InProcessTeammateNoSpawnError(TeamError):
    """An in-process teammate tried to spawn another teammate."""


class TeammateCancelledError(TeamError):
    """A teammate's async task was cancelled."""


# ──────────────────────────────────────────────
#  BackendType
# ──────────────────────────────────────────────

class BackendType(StrEnum):
    """Execution backend for a teammate."""

    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


# ──────────────────────────────────────────────
#  TeammateInfo — lightweight member record
# ──────────────────────────────────────────────

@dataclass
class TeammateInfo:
    name: str
    agent_id: str = ""
    agent_type: str = ""
    model: str = ""
    worktree_path: str = ""
    branch: str = ""
    backend_type: str = BackendType.IN_PROCESS
    pane_id: str = ""
    is_active: bool | None = None
    plan_mode_required: bool = False
    session_dir: str = ""
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": self.backend_type,
            "pane_id": self.pane_id,
            "is_active": self.is_active,
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeammateInfo:
        return cls(
            name=data.get("name", ""),
            agent_id=data.get("agent_id", ""),
            agent_type=data.get("agent_type", ""),
            model=data.get("model", ""),
            worktree_path=data.get("worktree_path", ""),
            branch=data.get("branch", ""),
            backend_type=data.get("backend_type", BackendType.IN_PROCESS),
            pane_id=data.get("pane_id", ""),
            is_active=data.get("is_active", None),
            plan_mode_required=data.get("plan_mode_required", False),
            session_dir=data.get("session_dir", ""),
            started_at=data.get("started_at", ""),
        )


# ──────────────────────────────────────────────
#  Team — persistent team object
# ──────────────────────────────────────────────

@dataclass
class Team:
    name: str
    sanitized_name: str
    lead_agent_id: str = "lead"
    backend: str = BackendType.IN_PROCESS
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    members: list[TeammateInfo] = field(default_factory=list)
    config_dir: str = ""
    config_path: str = ""
    tasks_path: str = ""
    mailbox_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "lead_agent_id": self.lead_agent_id,
            "backend": self.backend,
            "description": self.description,
            "created_at": self.created_at,
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        members_data = data.get("members", [])
        return cls(
            name=data.get("name", ""),
            sanitized_name=data.get("sanitized_name", ""),
            lead_agent_id=data.get("lead_agent_id", "lead"),
            backend=data.get("backend", BackendType.IN_PROCESS),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            members=[TeammateInfo.from_dict(m) for m in members_data],
        )

    def member_by_name(self, name: str) -> TeammateInfo | None:
        for m in self.members:
            if m.name == name:
                return m
        return None

    def member_by_agent_id(self, agent_id: str) -> TeammateInfo | None:
        for m in self.members:
            if m.agent_id == agent_id:
                return m
        return None

    def has_active_members(self) -> bool:
        for m in self.members:
            if m.name == "lead":
                continue
            if m.is_active in (True, None):
                return True
        return False

    def active_count(self) -> int:
        count = 0
        for m in self.members:
            if m.name == "lead":
                continue
            if m.is_active in (True, None):
                count += 1
        return count


# ──────────────────────────────────────────────
#  Message types (for mailbox + team-wide)
# ──────────────────────────────────────────────

class MessageType(StrEnum):
    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


@dataclass
class TeamMessage:
    from_: str
    to: str
    type: str = MessageType.TEXT
    summary: str = ""
    content: str = ""
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_,
            "to": self.to,
            "type": self.type,
            "summary": self.summary,
            "content": self.content,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamMessage:
        return cls(
            from_=data.get("from", ""),
            to=data.get("to", ""),
            type=data.get("type", MessageType.TEXT),
            summary=data.get("summary", ""),
            content=data.get("content", ""),
            payload=data.get("payload", None),
            timestamp=data.get("timestamp", 0),
            read=data.get("read", False),
        )


# ──────────────────────────────────────────────
#  Task types (shared team task list)
# ──────────────────────────────────────────────

class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class TeamTask:
    id: str
    title: str = ""
    description: str = ""
    status: str = TaskStatus.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "assignee": self.assignee,
            "blocked_by": list(self.blocked_by),
            "blocks": list(self.blocks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamTask:
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", TaskStatus.PENDING),
            assignee=data.get("assignee", ""),
            blocked_by=list(data.get("blocked_by", [])),
            blocks=list(data.get("blocks", [])),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
        )