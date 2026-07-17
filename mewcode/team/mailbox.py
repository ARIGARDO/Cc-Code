"""Team mailbox: per-agent message files with file-lock protection."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mewcode.team.filelock import acquire_lock
from mewcode.team.types import MessageType, TeamMessage


class Mailbox:
    """Thread and process-safe message box for a single team.

    Messages are stored as ``<mailbox_dir>/<agent_id>.json`` files containing
    a JSON array of message objects.  Reads and writes are guarded by an
    adjacent ``<agent_id>.lock`` file so that different processes / async
    tasks cannot corrupt the data.
    """

    def __init__(self, directory: str) -> None:
        self._dir = directory
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    # ── core read/write ────────────────────────

    async def write(self, agent_id: str, msg: TeamMessage) -> None:
        """Append ``msg`` to ``agent_id``'s message file."""

        if not msg.timestamp:
            msg.timestamp = int(time.time())

        lock_path = f"{self._dir}/{agent_id}.lock"
        file_path = f"{self._dir}/{agent_id}.json"

        async with acquire_lock(lock_path):
            messages = _load_messages(file_path)
            messages.append(msg)
            _save_messages(file_path, messages)

    async def write_many(
        self, targets: list[str], msg_factory
    ) -> None:
        """Send the same message to multiple agents.

        ``msg_factory(to)`` is called for each target so callers can set
        ``to`` correctly per recipient.
        """

        for to in targets:
            msg = msg_factory(to)
            await self.write(to, msg)

    async def read(self, agent_id: str) -> list[TeamMessage]:
        """Return all messages for ``agent_id`` (read-only copy)."""

        lock_path = f"{self._dir}/{agent_id}.lock"
        file_path = f"{self._dir}/{agent_id}.json"

        async with acquire_lock(lock_path):
            return _load_messages(file_path)

    async def read_unread(
        self, agent_id: str
    ) -> tuple[list[int], list[TeamMessage]]:
        """Return ``(indices, messages)`` for messages not yet marked read."""

        lock_path = f"{self._dir}/{agent_id}.lock"
        file_path = f"{self._dir}/{agent_id}.json"

        async with acquire_lock(lock_path):
            messages = _load_messages(file_path)
            indices = [i for i, m in enumerate(messages) if not m.read]
            return indices, [messages[i] for i in indices]

    async def mark_read(self, agent_id: str, indices: list[int]) -> None:
        """Mark the messages at ``indices`` as read."""

        if not indices:
            return

        lock_path = f"{self._dir}/{agent_id}.lock"
        file_path = f"{self._dir}/{agent_id}.json"

        async with acquire_lock(lock_path):
            messages = _load_messages(file_path)
            for i in indices:
                if 0 <= i < len(messages):
                    messages[i].read = True
            _save_messages(file_path, messages)


# ── local helpers ──────────────────────────────────

def _load_messages(file_path: str) -> list[TeamMessage]:
    path = Path(file_path)
    if not path.exists():
        return []
    try:
        import json as _json
        raw = _json.loads(path.read_text())
    except Exception:
        return []

    if not isinstance(raw, dict) or "messages" not in raw:
        return []

    msgs = raw["messages"]
    if not isinstance(msgs, list):
        return []

    result: list[TeamMessage] = []
    for item in msgs:
        if isinstance(item, dict):
            result.append(TeamMessage.from_dict(item))
    return result


def _save_messages(file_path: str, messages: list[TeamMessage]) -> None:
    import json as _json
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"messages": [m.to_dict() for m in messages]}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_json.dumps(data, indent=2))
    tmp.replace(path)


# ── convenience: build a TeamMessage quickly ────────

def build_text_message(from_: str, to: str, summary: str, content: str) -> TeamMessage:
    return TeamMessage(
        from_=from_,
        to=to,
        type=MessageType.TEXT,
        summary=summary,
        content=content,
    )


def build_plan_approval(
    from_: str,
    to: str,
    approve: bool,
    feedback: str = "",
) -> TeamMessage:
    return TeamMessage(
        from_=from_,
        to=to,
        type=MessageType.PLAN_APPROVAL_RESPONSE,
        summary="plan: " + ("approved" if approve else "rejected"),
        content=feedback,
        payload={"approve": bool(approve), "feedback": feedback},
    )


def build_shutdown_request(from_: str, to: str, reason: str = "") -> TeamMessage:
    return TeamMessage(
        from_=from_,
        to=to,
        type=MessageType.SHUTDOWN_REQUEST,
        summary="shutdown requested",
        content=reason,
    )


def build_shutdown_response(
    from_: str, to: str, approved: bool, reason: str = ""
) -> TeamMessage:
    return TeamMessage(
        from_=from_,
        to=to,
        type=MessageType.SHUTDOWN_RESPONSE,
        summary="shutdown " + ("ok" if approved else "denied"),
        content=reason,
        payload={"approve": bool(approved)},
    )