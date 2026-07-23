"""Session archival: JSONL persistence, metadata, resume, and cleanup."""

from __future__ import annotations

import datetime
import json
import logging
import random
import string
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from mewcode.conversation import (
    Message,
    ToolResultBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)

SESSIONS_DIR = ".mewcode/sessions"
TIME_GAP_THRESHOLD = datetime.timedelta(hours=24)
DEFAULT_MAX_AGE_DAYS = 30
TITLE_MAX_LENGTH = 50


class RecordType(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    COMPRESSION = "compression"


@dataclass
class SessionRecord:
    type: RecordType
    content: Any
    timestamp: datetime.datetime
    tool_use_id: Optional[str] = None
    is_error: bool = False

    def to_jsonl(self) -> str:
        data: dict[str, Any] = {
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.tool_use_id is not None:
            data["tool_use_id"] = self.tool_use_id
        if self.type == RecordType.TOOL_RESULT:
            data["is_error"] = self.is_error
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> Optional[SessionRecord]:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None
        try:
            rtype = RecordType(data["type"])
        except (KeyError, ValueError):
            return None
        try:
            ts = datetime.datetime.fromisoformat(data["timestamp"])
        except (KeyError, ValueError):
            return None
        return cls(
            type=rtype,
            content=data.get("content", ""),
            timestamp=ts,
            tool_use_id=data.get("tool_use_id"),
            is_error=data.get("is_error", False),
        )

    @classmethod
    def from_message(cls, message: Message) -> list[SessionRecord]:
        now = datetime.datetime.now(datetime.timezone.utc)
        records: list[SessionRecord] = []

        if message.role == "user" and message.tool_results:
            for tr in message.tool_results:
                records.append(cls(
                    type=RecordType.TOOL_RESULT,
                    content=tr.content,
                    timestamp=now,
                    tool_use_id=tr.tool_use_id,
                    is_error=tr.is_error,
                ))
            return records

        if message.role == "assistant" and message.tool_uses:
            content_blocks: list[dict[str, Any]] = []
            if message.content:
                content_blocks.append({"type": "text", "text": message.content})
            for tu in message.tool_uses:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tu.id,
                    "name": tu.name,
                    "input": tu.arguments,
                })
            records.append(cls(
                type=RecordType.ASSISTANT,
                content=content_blocks,
                timestamp=now,
            ))
            return records

        if message.role == "user":
            records.append(cls(
                type=RecordType.USER,
                content=message.content,
                timestamp=now,
            ))
        elif message.role == "assistant":
            records.append(cls(
                type=RecordType.ASSISTANT,
                content=message.content,
                timestamp=now,
            ))

        return records


def records_to_messages(records: list[SessionRecord]) -> list[Message]:
    messages: list[Message] = []
    pending_tool_results: list[ToolResultBlock] = []

    def _flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            messages.append(Message(role="user", tool_results=list(pending_tool_results)))
            pending_tool_results = []

    for rec in records:
        if rec.type == RecordType.SYSTEM_PROMPT:
            continue

        if rec.type == RecordType.TOOL_RESULT:
            pending_tool_results.append(ToolResultBlock(
                tool_use_id=rec.tool_use_id or "",
                content=rec.content if isinstance(rec.content, str) else str(rec.content),
                is_error=rec.is_error,
            ))
            continue

        _flush_tool_results()

        if rec.type == RecordType.COMPRESSION:
            text = rec.content if isinstance(rec.content, str) else str(rec.content)
            messages.append(Message(role="user", content=f"[摘要]\n{text}"))
            continue

        if rec.type == RecordType.USER:
            text = rec.content if isinstance(rec.content, str) else str(rec.content)
            messages.append(Message(role="user", content=text))
            continue

        if rec.type == RecordType.ASSISTANT:
            if isinstance(rec.content, list):
                text_parts: list[str] = []
                tool_uses: list[ToolUseBlock] = []
                for block in rec.content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_uses.append(ToolUseBlock(
                                id=block.get("id", ""),
                                name=block.get("name", ""),
                                arguments=block.get("input", {}),
                            ))
                messages.append(Message(
                    role="assistant",
                    content="\n".join(text_parts),
                    tool_uses=tool_uses,
                ))
            else:
                messages.append(Message(
                    role="assistant",
                    content=rec.content if isinstance(rec.content, str) else str(rec.content),
                ))

    _flush_tool_results()
    return messages


def validate_message_chain(records: list[SessionRecord]) -> int:
    pending_tool_uses: set[str] = set()
    max_complete = 0

    for i, rec in enumerate(records):
        if rec.type == RecordType.ASSISTANT and isinstance(rec.content, list):
            for block in rec.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id")
                    if tid:
                        pending_tool_uses.add(tid)

        if rec.type == RecordType.TOOL_RESULT and rec.tool_use_id:
            pending_tool_uses.discard(rec.tool_use_id)

        if not pending_tool_uses:
            max_complete = i + 1

    return max_complete


@dataclass
class SessionMeta:
    id: str
    title: str = ""
    summary: str = ""
    message_count: int = 0
    total_tokens: int = 0
    created_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    last_active: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def save(self, path: Path) -> None:
        data = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional[SessionMeta]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        try:
            return cls(
                id=data["id"],
                title=data.get("title", ""),
                summary=data.get("summary", ""),
                message_count=data.get("message_count", 0),
                total_tokens=data.get("total_tokens", 0),
                created_at=datetime.datetime.fromisoformat(data["created_at"]),
                last_active=datetime.datetime.fromisoformat(data["last_active"]),
            )
        except (KeyError, ValueError):
            return None


class Session:
    def __init__(
        self,
        session_id: str,
        file: Any,
        meta: SessionMeta,
        sessions_dir: Path,
    ) -> None:
        self.session_id = session_id
        self._file = file
        self.meta = meta
        self._sessions_dir = sessions_dir
        self._title_set = bool(meta.title)

    def append(self, message: Message) -> None:
        records = SessionRecord.from_message(message)
        for rec in records:
            line = rec.to_jsonl() + "\n"
            self._file.write(line)
            self._file.flush()

        self.meta.message_count += 1
        self.meta.last_active = datetime.datetime.now(datetime.timezone.utc)

        if not self._title_set and message.role == "user" and message.content:
            title = message.content.strip().replace("\n", " ")
            if len(title) > TITLE_MAX_LENGTH:
                title = title[:TITLE_MAX_LENGTH]
            self.meta.title = title
            self._title_set = True

        meta_path = self._sessions_dir / f"{self.session_id}.meta"
        self.meta.save(meta_path)

    def close(self) -> None:
        try:
            self._file.flush()
            self._file.close()
        except (ValueError, OSError):
            pass


SESSION_SUMMARY_PROMPT = """请用一句话总结以下对话的主要内容。不要调用任何工具。"""


async def generate_session_summary(
    client: Any,
    conversation: Any,
    protocol: str,
) -> str:
    try:
        recent = conversation.history[-10:]
        if not recent:
            return ""

        lines: list[str] = []
        for msg in recent:
            role_label = "用户" if msg.role == "user" else "助手"
            text = msg.content[:200] if msg.content else ""
            lines.append(f"{role_label}: {text}")

        prompt = (
            SESSION_SUMMARY_PROMPT
            + "\n\n## 最近对话\n"
            + "\n".join(lines)
            + "\n\n请给出一句话总结："
        )

        from mewcode.conversation import ConversationManager as CM
        conv = CM()
        conv.add_user_message(prompt)

        collected = ""
        stream = client.stream(conv, system="你是一个会话摘要助手。")
        async for event in stream:
            from mewcode.tools.base import TextDelta
            if isinstance(event, TextDelta):
                collected += event.text

        return collected.strip()
    except Exception:
        return ""


def build_time_gap_message(last_active: datetime.datetime) -> Optional[Message]:
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=datetime.timezone.utc)
    gap = now - last_active
    if gap < TIME_GAP_THRESHOLD:
        return None

    hours = int(gap.total_seconds() // 3600)
    if hours >= 48:
        days = hours // 24
        time_desc = f"{days} 天"
    else:
        time_desc = f"{hours} 小时"

    content = (
        f"距离上次会话已过去 {time_desc}。"
        f"代码可能有变更，建议在操作前重新读取相关文件。"
    )
    return Message(role="user", content=content)


def _generate_session_id() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"session_{stamp}_{suffix}"


@dataclass
class ResumeResult:
    session: Session
    messages: list[Message]
    last_active: datetime.datetime


class SessionManager:
    def __init__(self, work_dir: str | Path) -> None:
        self._sessions_dir = Path(work_dir) / SESSIONS_DIR
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> Session:
        session_id = _generate_session_id()
        meta = SessionMeta(id=session_id)
        meta_path = self._sessions_dir / f"{session_id}.meta"
        meta.save(meta_path)

        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        file = open(jsonl_path, "a", encoding="utf-8")

        return Session(
            session_id=session_id,
            file=file,
            meta=meta,
            sessions_dir=self._sessions_dir,
        )

    def list(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for meta_path in self._sessions_dir.glob("*.meta"):
            meta = SessionMeta.load(meta_path)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda m: m.last_active, reverse=True)
        return metas

    def resume(self, session_id: str) -> Optional[ResumeResult]:
        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        meta_path = self._sessions_dir / f"{session_id}.meta"

        if not jsonl_path.is_file():
            return None

        meta = SessionMeta.load(meta_path)
        if meta is None:
            meta = SessionMeta(id=session_id)

        records: list[SessionRecord] = []
        try:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = SessionRecord.from_jsonl(line)
                if rec is not None:
                    records.append(rec)
        except OSError:
            return None

        valid_len = validate_message_chain(records)
        if valid_len < len(records):
            records = records[:valid_len]

        messages = records_to_messages(records)

        file = open(jsonl_path, "a", encoding="utf-8")
        session = Session(
            session_id=session_id,
            file=file,
            meta=meta,
            sessions_dir=self._sessions_dir,
        )

        return ResumeResult(
            session=session,
            messages=messages,
            last_active=meta.last_active,
        )

    def delete(self, session_id: str) -> bool:
        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        meta_path = self._sessions_dir / f"{session_id}.meta"
        deleted = False
        try:
            if jsonl_path.exists():
                jsonl_path.unlink()
                deleted = True
        except OSError:
            pass
        try:
            if meta_path.exists():
                meta_path.unlink()
                deleted = True
        except OSError:
            pass
        return deleted

    def cleanup(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
        count = 0
        for meta in self.list():
            last = meta.last_active
            if last.tzinfo is None:
                last = last.replace(tzinfo=datetime.timezone.utc)
            if last < cutoff:
                if self.delete(meta.id):
                    count += 1
        return count