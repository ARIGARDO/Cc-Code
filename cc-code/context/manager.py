"""Context management — two-layer budget + auto-compact + recovery.

Layer 1 (apply_tool_result_budget): cheap local-only, every turn.
  - Persist oversized tool results to disk, replace with preview.
  - Aggregate budget: if total tool-result chars exceed limit, persist largest.
  - Snip stale old results.
  - Byte-stable: once a replacement is decided, it is replayed verbatim.

Layer 2 (auto_compact): LLM-powered summary when approaching context limit.
  - CompactCircuitBreaker prevents runaway failures.
  - PTL retry drops oldest 1/5 turns.

Recovery (RecoveryState): post-compact working-memory restoration.
  - Tracks recently-read files and activated skills.
  - build_recovery_attachment renders them into the compact summary.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mewcode.conversation import ConversationManager, Message, ToolResultBlock

# ──────────────────────────────────────────────
#  Constants (T1)
# ──────────────────────────────────────────────

SINGLE_RESULT_CHAR_LIMIT = 5_000
AGGREGATE_CHAR_LIMIT = 20_000
PREVIEW_CHARS = 2_000
KEEP_RECENT_TURNS = 10
OLD_RESULT_SNIP_CHARS = 2_000
SNIPPED_TAG = "<snipped>"

SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_SAFETY_MARGIN = 13_000
MANUAL_COMPACT_SAFETY_MARGIN = 3_000
PERSISTED_TAG = "<persisted-output>"
SESSION_SUBDIR = ".mewcode/session/tool-results"

RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
RECOVERY_SKILLS_BUDGET = 25_000
RECOVERY_TOKENS_PER_SKILL = 5_000
_RECOVERY_CHARS_PER_TOKEN = 3.5

# ──────────────────────────────────────────────
#  State containers (T2)
# ──────────────────────────────────────────────


@dataclass
class CompactEvent:
    before_tokens: int


@dataclass
class ContentReplacementState:
    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentReplacementRecord:
    tool_use_id: str
    replacement: str
    kind: str = "tool-result"
    original_chars: int = 0


# ──────────────────────────────────────────────
#  State factories (T3)
# ──────────────────────────────────────────────


def create_replacement_state() -> ContentReplacementState:
    return ContentReplacementState()


def clone_replacement_state(src: ContentReplacementState) -> ContentReplacementState:
    return ContentReplacementState(
        seen_ids=set(src.seen_ids),
        replacements=dict(src.replacements),
    )


# ──────────────────────────────────────────────
#  Transcript JSONL I/O (T4)
# ──────────────────────────────────────────────

REPLACEMENT_RECORDS_FILENAME = "replacement_records.jsonl"


def append_replacement_records(
    session_dir: Path, records: list[ContentReplacementRecord]
) -> None:
    if not records:
        return
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            obj = {
                "kind": r.kind,
                "tool_use_id": r.tool_use_id,
                "replacement": r.replacement,
                "original_chars": r.original_chars,
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_replacement_records(session_dir: Path) -> list[ContentReplacementRecord]:
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    if not path.exists():
        return []
    records: list[ContentReplacementRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append(
                ContentReplacementRecord(
                    tool_use_id=obj["tool_use_id"],
                    replacement=obj["replacement"],
                    kind=obj.get("kind", "tool-result"),
                    original_chars=obj.get("original_chars", 0),
                )
            )
    return records


# ──────────────────────────────────────────────
#  Reconstruct state from records (T5)
# ──────────────────────────────────────────────


def reconstruct_replacement_state(
    messages: list[Message],
    records: list[ContentReplacementRecord],
    inherited_replacements: Optional[dict[str, str]] = None,
) -> ContentReplacementState:
    seen_ids: set[str] = set()
    for m in messages:
        for tr in m.tool_results:
            seen_ids.add(tr.tool_use_id)

    replacements: dict[str, str] = {}
    for r in records:
        if r.kind == "tool-result" and r.tool_use_id in seen_ids:
            replacements[r.tool_use_id] = r.replacement

    if inherited_replacements:
        for k, v in inherited_replacements.items():
            if k in seen_ids and k not in replacements:
                replacements[k] = v

    return ContentReplacementState(seen_ids=seen_ids, replacements=replacements)


# ──────────────────────────────────────────────
#  Session helpers (T1)
# ──────────────────────────────────────────────


def ensure_session_dir(work_dir: Path) -> Path:
    p = work_dir / SESSION_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def cleanup_tool_results(session_dir: Path) -> None:
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
#  Layer 1: persist + preview (T6)
# ──────────────────────────────────────────────


def persist_tool_result(
    tool_use_id: str, content: str, session_dir: Path
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / f"{tool_use_id}.txt"
    try:
        fd = os.open(
            str(file_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        pass
    return file_path


def make_persisted_preview(content: str, file_path: Path) -> str:
    kb = len(content.encode("utf-8")) / 1024
    preview = content[:PREVIEW_CHARS]
    return (
        f"{PERSISTED_TAG}\n"
        f"输出太大（{kb:.1f}KB），完整内容已保存到：\n"
        f"{file_path}\n\n"
        f"预览（前 2KB）：\n"
        f"{preview}\n"
        f"</persisted-output>"
    )


# ──────────────────────────────────────────────
#  Layer 1: helpers (T7)
# ──────────────────────────────────────────────


def _count_turns(messages: list[Message]) -> int:
    turns = 0
    for m in messages:
        if m.role == "assistant" and not m.tool_uses:
            turns += 1
    return turns


def _copy_message_with_results(
    msg: Message, new_tool_results: list[ToolResultBlock]
) -> Message:
    return Message(
        role=msg.role,
        content=msg.content,
        tool_uses=msg.tool_uses,
        tool_results=new_tool_results,
        thinking_blocks=msg.thinking_blocks,
    )


def _snip_stale_messages(history: list[Message]) -> list[Message]:
    total_turns = _count_turns(history)
    if total_turns <= KEEP_RECENT_TURNS:
        return history

    turn_idx = 0
    new_history: list[Message] = []
    for m in history:
        if m.role == "assistant" and not m.tool_uses:
            turn_idx += 1
        is_stale = turn_idx <= (total_turns - KEEP_RECENT_TURNS)

        if is_stale and m.tool_results:
            new_trs: list[ToolResultBlock] = []
            for tr in m.tool_results:
                if (
                    len(tr.content) > OLD_RESULT_SNIP_CHARS
                    and not tr.content.startswith(PERSISTED_TAG)
                    and not tr.content.startswith(SNIPPED_TAG)
                ):
                    snippet = (
                        f"{SNIPPED_TAG}\n"
                        f"(旧结果已裁剪，原始长度 {len(tr.content)} 字符)\n"
                        f"{tr.content[:200]}\n"
                        f"… (snipped)"
                    )
                    new_trs.append(
                        ToolResultBlock(
                            tool_use_id=tr.tool_use_id,
                            content=snippet,
                            is_error=tr.is_error,
                        )
                    )
                else:
                    new_trs.append(tr)
            new_history.append(_copy_message_with_results(m, new_trs))
        else:
            new_history.append(m)

    return new_history


# ──────────────────────────────────────────────
#  Layer 1: apply_tool_result_budget (T8)
# ──────────────────────────────────────────────


def apply_tool_result_budget(
    conversation: ConversationManager,
    session_dir: Path,
    state: ContentReplacementState,
) -> tuple[ConversationManager, list[ContentReplacementRecord]]:
    new_records: list[ContentReplacementRecord] = []
    decisions: dict[str, str] = {}

    for m in conversation.history:
        for tr in m.tool_results:
            tid = tr.tool_use_id

            if tid in state.replacements:
                decisions[tid] = state.replacements[tid]
                continue

            if tid in state.seen_ids:
                decisions[tid] = tr.content
                continue

            if tr.content.startswith(PERSISTED_TAG):
                state.seen_ids.add(tid)
                state.replacements[tid] = tr.content
                decisions[tid] = tr.content
                new_records.append(
                    ContentReplacementRecord(
                        tool_use_id=tid,
                        replacement=tr.content,
                        original_chars=len(tr.content),
                    )
                )
                continue

    fresh: list[tuple[str, str]] = []
    for m in conversation.history:
        for tr in m.tool_results:
            tid = tr.tool_use_id
            if tid in decisions:
                continue
            if tid not in state.seen_ids:
                fresh.append((tid, tr.content))

    for tid, content in fresh:
        if len(content) > SINGLE_RESULT_CHAR_LIMIT:
            file_path = persist_tool_result(tid, content, session_dir)
            preview = make_persisted_preview(content, file_path)
            state.seen_ids.add(tid)
            state.replacements[tid] = preview
            decisions[tid] = preview
            new_records.append(
                ContentReplacementRecord(
                    tool_use_id=tid,
                    replacement=preview,
                    original_chars=len(content),
                )
            )

    remaining_fresh = [
        (tid, content)
        for tid, content in fresh
        if tid not in decisions
    ]

    total = sum(len(decisions.get(tid, content)) for tid, content in remaining_fresh)
    total += sum(len(v) for v in decisions.values())

    if total > AGGREGATE_CHAR_LIMIT and remaining_fresh:
        sorted_fresh = sorted(remaining_fresh, key=lambda x: len(x[1]), reverse=True)
        kept_total = sum(len(v) for v in decisions.values())
        for tid, content in sorted_fresh:
            if kept_total + len(content) <= AGGREGATE_CHAR_LIMIT:
                kept_total += len(content)
            else:
                file_path = persist_tool_result(tid, content, session_dir)
                preview = make_persisted_preview(content, file_path)
                state.seen_ids.add(tid)
                state.replacements[tid] = preview
                decisions[tid] = preview
                new_records.append(
                    ContentReplacementRecord(
                        tool_use_id=tid,
                        replacement=preview,
                        original_chars=len(content),
                    )
                )

    for tid, content in fresh:
        if tid not in decisions:
            state.seen_ids.add(tid)
            decisions[tid] = content

    new_history: list[Message] = []
    for m in conversation.history:
        if m.tool_results:
            new_trs: list[ToolResultBlock] = []
            for tr in m.tool_results:
                content = decisions.get(tr.tool_use_id, tr.content)
                new_trs.append(
                    ToolResultBlock(
                        tool_use_id=tr.tool_use_id,
                        content=content,
                        is_error=tr.is_error,
                    )
                )
            new_history.append(_copy_message_with_results(m, new_trs))
        else:
            new_history.append(m)

    new_history = _snip_stale_messages(new_history)

    api_conv = ConversationManager(
        history=new_history,
        env_injected=conversation.env_injected,
        ltm_injected=conversation.ltm_injected,
        last_input_tokens=conversation.last_input_tokens,
    )

    return api_conv, new_records


# ──────────────────────────────────────────────
#  Layer 2: threshold (T9)
# ──────────────────────────────────────────────


def compute_compact_threshold(
    context_window: int, manual: bool = False
) -> int:
    margin = MANUAL_COMPACT_SAFETY_MARGIN if manual else AUTO_COMPACT_SAFETY_MARGIN
    return context_window - SUMMARY_OUTPUT_RESERVE - margin


def should_auto_compact(
    last_input_tokens: int, context_window: int
) -> bool:
    return last_input_tokens >= compute_compact_threshold(context_window)


# ──────────────────────────────────────────────
#  Layer 2: summary prompt + helpers (T10)
# ──────────────────────────────────────────────

SUMMARY_PROMPT = """\
你是一个会话摘要助手。请对以下对话历史生成一份结构化摘要。

摘要必须包含以下九节（用 markdown 二级标题）：
## 主要请求
用户的核心请求和目标。

## 关键概念
对话中涉及的关键技术概念、术语和设计决策。

## 文件与代码段
讨论或修改过的文件路径、代码片段和变更内容。

## 错误与修复
遇到的所有错误及其解决方案。

## 解决过程
问题解决的步骤和推理过程。

## 用户原话
用户的关键原话引用（保留原文）。

## 待办
尚未完成的任务和待处理事项。

## 当前工作
当前正在进行的任务状态。

## 下一步
接下来需要执行的操作。

重要规则：
1. 不要调用任何工具。
2. 先在 <analysis> 标签内分析对话，再在 <summary> 标签内输出摘要。
3. 摘要应保留足够细节以便继续工作，但远短于原文。
"""


def extract_summary(llm_output: str) -> str:
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start != -1 and end != -1 and end > start:
        return llm_output[start + len("<summary>"):end].strip()
    return llm_output.strip()


COMPACT_BOUNDARY_MESSAGE = (
    "上下文已压缩。以上是之前对话的摘要，请基于摘要继续工作。"
)


def build_compact_messages(
    summary: str, attachment: str = ""
) -> list[Message]:
    user_content = f"[摘要]\n{summary}"
    if attachment:
        user_content += f"\n\n---\n\n{attachment}"
    return [
        Message(role="user", content=user_content),
        Message(role="assistant", content=COMPACT_BOUNDARY_MESSAGE),
    ]


def _group_messages_by_turn(messages: list[Message]) -> list[list[Message]]:
    turns: list[list[Message]] = []
    current: list[Message] = []
    for m in messages:
        current.append(m)
        if m.role == "assistant" and not m.tool_uses:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


# ──────────────────────────────────────────────
#  Layer 2: circuit breaker (T11)
# ──────────────────────────────────────────────


@dataclass
class CompactCircuitBreaker:
    max_failures: int = 3
    consecutive_failures: int = field(init=False, default=0)

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def is_open(self) -> bool:
        return self.consecutive_failures >= self.max_failures


# ──────────────────────────────────────────────
#  Layer 2: auto_compact (T12)
# ──────────────────────────────────────────────


async def auto_compact(
    conversation: ConversationManager,
    client: Any,
    context_window: int,
    session_dir: Path,
    protocol: str = "anthropic",
    manual: bool = False,
    breaker: Optional[CompactCircuitBreaker] = None,
    recovery: Optional[RecoveryState] = None,
    tool_schemas: Optional[list[Any]] = None,
) -> Optional[str | CompactEvent]:
    threshold = compute_compact_threshold(context_window, manual=manual)

    if not manual and conversation.last_input_tokens < threshold:
        return None

    if breaker is not None and breaker.is_open():
        return "压缩熔断器已开启，跳过自动压缩"

    from mewcode.tools.base import TextDelta, StreamEnd

    max_retries = 3
    for attempt in range(max_retries):
        summary_conv = ConversationManager()
        summary_conv.add_user_message(SUMMARY_PROMPT)
        for m in conversation.history:
            summary_conv.history.append(m)
        summary_conv.add_user_message(
            "请基于以上对话生成摘要。不要调用任何工具。先输出 <analysis>，再输出 <summary>。"
        )

        try:
            full_text = ""
            stream = client.stream(summary_conv, system=SUMMARY_PROMPT, tools=None)
            async for event in stream:
                if isinstance(event, TextDelta):
                    full_text += event.text
                elif isinstance(event, StreamEnd):
                    pass

            summary = extract_summary(full_text)

            attachment = ""
            if recovery is not None or tool_schemas is not None:
                attachment = build_recovery_attachment(
                    recovery or RecoveryState(), tool_schemas
                )

            new_messages = build_compact_messages(summary, attachment=attachment)
            conversation.replace_history(new_messages)
            cleanup_tool_results(session_dir)

            if breaker is not None:
                breaker.record_success()

            return CompactEvent(before_tokens=conversation.last_input_tokens)

        except Exception as e:
            err_msg = str(e).lower()
            if "prompt" in err_msg and "long" in err_msg:
                turns = _group_messages_by_turn(conversation.history)
                if len(turns) > 1:
                    drop_count = max(1, len(turns) // 5)
                    kept = turns[drop_count:]
                    conversation.replace_history(
                        [m for t in kept for m in t]
                    )
                    continue

            if breaker is not None:
                breaker.record_failure()
            return f"压缩失败: {e}"

    if breaker is not None:
        breaker.record_failure()
    return "压缩失败: 多次重试后仍无法生成摘要"


# ──────────────────────────────────────────────
#  Recovery state (T18)
# ──────────────────────────────────────────────


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: float


@dataclass
class SkillInvocationRecord:
    name: str
    body: str
    timestamp: float


class RecoveryState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileReadRecord] = {}
        self._skills: dict[str, SkillInvocationRecord] = {}

    def record_file_read(self, path: str, content: str) -> None:
        if not path:
            return
        with self._lock:
            self._files[path] = FileReadRecord(
                path=path, content=content, timestamp=time.time()
            )

    def record_skill_invocation(self, name: str, body: str) -> None:
        if not name:
            return
        with self._lock:
            self._skills[name] = SkillInvocationRecord(
                name=name, body=body, timestamp=time.time()
            )

    def snapshot_files(self, limit: int = RECOVERY_FILE_LIMIT) -> list[FileReadRecord]:
        with self._lock:
            items = sorted(
                self._files.values(), key=lambda r: r.timestamp, reverse=True
            )
        return items[:limit]

    def snapshot_skills(self) -> list[SkillInvocationRecord]:
        with self._lock:
            return sorted(
                self._skills.values(), key=lambda r: r.timestamp, reverse=True
            )


# ──────────────────────────────────────────────
#  Recovery helpers (T19)
# ──────────────────────────────────────────────


def _approx_tokens(s: str) -> int:
    return int(len(s) / _RECOVERY_CHARS_PER_TOKEN)


def _truncate_by_tokens(s: str, budget: int) -> str:
    max_chars = int(budget * _RECOVERY_CHARS_PER_TOKEN)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n… (内容已截断)"


def _first_line(s: str) -> str:
    for line in s.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_recovery_attachment(
    state: RecoveryState,
    tool_schemas: Optional[list[Any]] = None,
) -> str:
    sections: list[str] = []

    files = state.snapshot_files(RECOVERY_FILE_LIMIT)
    if files:
        lines = ["## 最近读过的文件"]
        for f in files:
            truncated = _truncate_by_tokens(f.content, RECOVERY_TOKENS_PER_FILE)
            lines.append(f"### {f.path}")
            lines.append(f"```\n{truncated}\n```")
        sections.append("\n".join(lines))

    skills = state.snapshot_skills()
    if skills:
        lines = ["## 已激活的技能"]
        skill_chars = 0
        budget_chars = int(RECOVERY_SKILLS_BUDGET * _RECOVERY_CHARS_PER_TOKEN)
        for s in skills:
            truncated = _truncate_by_tokens(s.body, RECOVERY_TOKENS_PER_SKILL)
            entry = f"### {s.name}\n```\n{truncated}\n```"
            if skill_chars + len(entry) > budget_chars:
                break
            lines.append(entry)
            skill_chars += len(entry)
        sections.append("\n".join(lines))

    if tool_schemas:
        lines = ["## 可用工具"]
        for schema in tool_schemas:
            name = schema.get("name", "")
            desc = ""
            if "description" in schema:
                desc = _first_line(schema["description"])
            lines.append(f"- {name} — {desc}" if desc else f"- {name}")
        sections.append("\n".join(lines))

    sections.append(
        "## 提示\n"
        "以上是压缩前的工作记忆摘要。如需查看完整文件内容，请重新读取文件，不要仅凭摘要猜测。"
    )

    return "\n\n".join(sections)


# ──────────────────────────────────────────────
#  manual_compact (F15)
# ──────────────────────────────────────────────


async def manual_compact(
    conversation: ConversationManager,
    client: Any,
    context_window: int,
    session_dir: Path,
    protocol: str = "anthropic",
    breaker: Optional[CompactCircuitBreaker] = None,
    recovery: Optional[RecoveryState] = None,
    tool_schemas: Optional[list[Any]] = None,
) -> Optional[str | CompactEvent]:
    return await auto_compact(
        conversation,
        client,
        context_window,
        session_dir,
        protocol=protocol,
        manual=True,
        breaker=breaker,
        recovery=recovery,
        tool_schemas=tool_schemas,
    )