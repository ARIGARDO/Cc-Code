"""Tests for ch09 memory system: instructions, session, auto_memory."""

from __future__ import annotations

import datetime
from pathlib import Path


from cccode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
    ToolUseBlock,
)
from cccode.memory.instructions import (
    MAX_INCLUDE_DEPTH,
    load_instructions,
    process_includes,
)
from cccode.memory.session import (
    RecordType,
    SessionRecord,
    SessionMeta,
    Session,
    SessionManager,
    build_time_gap_message,
    records_to_messages,
    validate_message_chain,
    TITLE_MAX_LENGTH,
)
from cccode.memory.auto_memory import (
    MemoryManager,
    MEMORY_EXTRACTION_PROMPT,
)


# ──────────────────────────────────────────────
#  TestProcessIncludes
# ──────────────────────────────────────────────

class TestProcessIncludes:
    def test_no_includes(self):
        content = "Hello\nWorld"
        result = process_includes(content, Path("."), Path("."))
        assert result == "Hello\nWorld"

    def test_basic(self, tmp_path):
        sub = tmp_path / "sub.md"
        sub.write_text("Included content", encoding="utf-8")
        content = "@include sub.md"
        result = process_includes(content, tmp_path, tmp_path)
        assert "Included content" in result

    def test_recursive(self, tmp_path):
        inner = tmp_path / "inner.md"
        inner.write_text("Inner content", encoding="utf-8")
        outer = tmp_path / "outer.md"
        outer.write_text("@include inner.md", encoding="utf-8")
        content = "@include outer.md"
        result = process_includes(content, tmp_path, tmp_path)
        assert "Inner content" in result

    def test_depth_limit(self, tmp_path):
        circular = tmp_path / "circular.md"
        circular.write_text("@include circular.md", encoding="utf-8")
        content = "@include circular.md"
        result = process_includes(content, tmp_path, tmp_path, depth=MAX_INCLUDE_DEPTH)
        assert "@include circular.md" in result

    def test_path_outside_project_blocked(self, tmp_path):
        content = "@include ../../etc/passwd"
        result = process_includes(content, tmp_path, tmp_path)
        assert "<!-- @include blocked: path outside project -->" in result

    def test_file_not_found(self, tmp_path):
        content = "@include nonexistent.md"
        result = process_includes(content, tmp_path, tmp_path)
        assert "<!-- @include skipped: file not found -->" in result


# ──────────────────────────────────────────────
#  TestLoadInstructions
# ──────────────────────────────────────────────

class TestLoadInstructions:
    def test_single_layer(self, tmp_path):
        cccode_md = tmp_path / "CCCODE.md"
        cccode_md.write_text("Project instructions here", encoding="utf-8")
        result = load_instructions(tmp_path)
        assert "Project instructions here" in result

    def test_multi_layer_priority(self, tmp_path):
        root_md = tmp_path / "CCCODE.md"
        root_md.write_text("Root level", encoding="utf-8")
        dot_md = tmp_path / ".cccode" / "CCCODE.md"
        dot_md.parent.mkdir(parents=True, exist_ok=True)
        dot_md.write_text("Dot level", encoding="utf-8")
        result = load_instructions(tmp_path)
        assert "Root level" in result
        assert "Dot level" in result
        assert "---" in result

    def test_no_files_returns_empty(self, tmp_path):
        result = load_instructions(tmp_path)
        assert result == ""


# ──────────────────────────────────────────────
#  TestSessionRecord
# ──────────────────────────────────────────────

class TestSessionRecord:
    def test_user_roundtrip(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        rec = SessionRecord(type=RecordType.USER, content="hello", timestamp=now)
        line = rec.to_jsonl()
        restored = SessionRecord.from_jsonl(line)
        assert restored is not None
        assert restored.type == RecordType.USER
        assert restored.content == "hello"

    def test_assistant_with_tool_uses(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        content = [
            {"type": "text", "text": "I'll help"},
            {"type": "tool_use", "id": "tu1", "name": "ReadFile", "input": {"path": "a.py"}},
        ]
        rec = SessionRecord(type=RecordType.ASSISTANT, content=content, timestamp=now)
        line = rec.to_jsonl()
        restored = SessionRecord.from_jsonl(line)
        assert restored is not None
        assert restored.type == RecordType.ASSISTANT
        assert isinstance(restored.content, list)
        assert len(restored.content) == 2

    def test_tool_results_multiple_records(self):
        msg = Message(
            role="user",
            tool_results=[
                ToolResultBlock(tool_use_id="t1", content="result1"),
                ToolResultBlock(tool_use_id="t2", content="result2", is_error=True),
            ],
        )
        records = SessionRecord.from_message(msg)
        assert len(records) == 2
        assert records[0].tool_use_id == "t1"
        assert records[1].is_error is True

    def test_malformed_jsonl(self):
        assert SessionRecord.from_jsonl("not json") is None
        assert SessionRecord.from_jsonl("{}") is None
        assert SessionRecord.from_jsonl('{"type":"unknown","content":"","timestamp":"2024-01-01T00:00:00+00:00"}') is None

    def test_plain_assistant(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        rec = SessionRecord(type=RecordType.ASSISTANT, content="Hello!", timestamp=now)
        line = rec.to_jsonl()
        restored = SessionRecord.from_jsonl(line)
        assert restored is not None
        assert restored.content == "Hello!"


# ──────────────────────────────────────────────
#  TestRecordsToMessages
# ──────────────────────────────────────────────

class TestRecordsToMessages:
    def test_basic_roundtrip(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
            SessionRecord(type=RecordType.ASSISTANT, content="hello", timestamp=now),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "hi"
        assert messages[1].role == "assistant"

    def test_tool_result_grouping(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        records = [
            SessionRecord(type=RecordType.ASSISTANT, content=[
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
            ], timestamp=now),
            SessionRecord(type=RecordType.TOOL_RESULT, content="output", timestamp=now, tool_use_id="t1"),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 2
        assert messages[1].role == "user"
        assert len(messages[1].tool_results) == 1

    def test_system_prompt_skipped(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        records = [
            SessionRecord(type=RecordType.SYSTEM_PROMPT, content="sys", timestamp=now),
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 1
        assert messages[0].content == "hi"


# ──────────────────────────────────────────────
#  TestValidateMessageChain
# ──────────────────────────────────────────────

class TestValidateMessageChain:
    def test_complete_chain(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
            SessionRecord(type=RecordType.ASSISTANT, content=[
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
            ], timestamp=now),
            SessionRecord(type=RecordType.TOOL_RESULT, content="ok", timestamp=now, tool_use_id="t1"),
        ]
        assert validate_message_chain(records) == 3

    def test_truncate_at_missing_tool_result(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
            SessionRecord(type=RecordType.ASSISTANT, content=[
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
            ], timestamp=now),
        ]
        assert validate_message_chain(records) == 1

    def test_empty_records(self):
        assert validate_message_chain([]) == 0


# ──────────────────────────────────────────────
#  TestSession
# ──────────────────────────────────────────────

class TestSession:
    def test_append_writes_jsonl_and_updates_meta(self, tmp_path):
        sessions_dir = tmp_path / ".cccode" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        meta = SessionMeta(id="test_session")
        jsonl_path = sessions_dir / "test_session.jsonl"
        f = open(jsonl_path, "a", encoding="utf-8")
        session = Session(session_id="test_session", file=f, meta=meta, sessions_dir=sessions_dir)

        msg = Message(role="user", content="Hello world")
        session.append(msg)
        session.close()

        content = jsonl_path.read_text(encoding="utf-8")
        assert "Hello world" in content
        assert meta.message_count == 1

    def test_title_set_from_first_user_message(self, tmp_path):
        sessions_dir = tmp_path / ".cccode" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        meta = SessionMeta(id="test_session2")
        jsonl_path = sessions_dir / "test_session2.jsonl"
        f = open(jsonl_path, "a", encoding="utf-8")
        session = Session(session_id="test_session2", file=f, meta=meta, sessions_dir=sessions_dir)

        msg = Message(role="user", content="This is a long title that should be truncated to fit within the max length limit")
        session.append(msg)
        session.close()

        assert len(session.meta.title) == TITLE_MAX_LENGTH
        assert session.meta.title == "This is a long title that should be truncated to f"


# ──────────────────────────────────────────────
#  TestSessionManager
# ──────────────────────────────────────────────

class TestSessionManager:
    def test_create_and_list(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        assert session.session_id.startswith("session_")
        metas = mgr.list()
        assert len(metas) >= 1
        session.close()

    def test_delete(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        sid = session.session_id
        session.close()
        assert mgr.delete(sid) is True
        assert mgr.delete(sid) is False

    def test_cleanup_removes_old_sessions(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        session.meta.last_active = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
        meta_path = mgr._sessions_dir / f"{session.session_id}.meta"
        session.meta.save(meta_path)
        session.close()
        count = mgr.cleanup(max_age_days=30)
        assert count >= 1

    def test_create_generates_valid_id(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        sid = session.session_id
        assert sid.startswith("session_")
        parts = sid.split("_")
        assert len(parts) == 4
        assert len(parts[3]) == 4
        session.close()


# ──────────────────────────────────────────────
#  TestSessionResume
# ──────────────────────────────────────────────

class TestSessionResume:
    def test_restores_messages(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        session.append(Message(role="user", content="Hello"))
        session.append(Message(role="assistant", content="Hi there"))
        session.close()

        result = mgr.resume(session.session_id)
        assert result is not None
        assert len(result.messages) >= 1

    def test_nonexistent_returns_none(self, tmp_path):
        mgr = SessionManager(tmp_path)
        result = mgr.resume("nonexistent_id")
        assert result is None

    def test_truncates_incomplete_chain(self, tmp_path):
        mgr = SessionManager(tmp_path)
        session = mgr.create()
        session.append(Message(role="user", content="Hello"))
        session.append(Message(
            role="assistant",
            content="",
            tool_uses=[ToolUseBlock(id="t1", name="Read", arguments={})],
        ))
        session.close()

        result = mgr.resume(session.session_id)
        assert result is not None
        assert len(result.messages) == 1


# ──────────────────────────────────────────────
#  TestTimeGapMessage
# ──────────────────────────────────────────────

class TestTimeGapMessage:
    def test_no_gap_returns_none(self):
        recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        assert build_time_gap_message(recent) is None

    def test_gap_returns_message(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
        msg = build_time_gap_message(old)
        assert msg is not None
        assert "天" in msg.content
        assert "代码可能有变更" in msg.content

    def test_gap_hours(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)
        msg = build_time_gap_message(old)
        assert msg is not None
        assert "小时" in msg.content


# ──────────────────────────────────────────────
#  TestMemoryManager
# ──────────────────────────────────────────────

class TestMemoryManager:
    def test_load_empty(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        mgr._user_path = tmp_path / "user_memories.md"
        mgr._project_path = tmp_path / "project_memories.md"
        assert mgr.load() == ""

    def test_load_merges_user_and_project(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        mgr._user_path.parent.mkdir(parents=True, exist_ok=True)
        mgr._user_path.write_text("User memory", encoding="utf-8")
        mgr._project_path.parent.mkdir(parents=True, exist_ok=True)
        mgr._project_path.write_text("Project memory", encoding="utf-8")
        result = mgr.load()
        assert "User memory" in result
        assert "Project memory" in result

    def test_clear(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        mgr._user_path.parent.mkdir(parents=True, exist_ok=True)
        mgr._user_path.write_text("Some memory", encoding="utf-8")
        mgr._project_path.parent.mkdir(parents=True, exist_ok=True)
        mgr._project_path.write_text("Project memory", encoding="utf-8")
        mgr.clear()
        assert mgr._user_path.read_text(encoding="utf-8") == ""
        assert mgr._project_path.read_text(encoding="utf-8") == ""

    def test_get_display_text_empty(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        assert mgr.get_display_text() == "当前没有任何自动记忆。"

    def test_get_display_text_with_content(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        mgr._user_path.parent.mkdir(parents=True, exist_ok=True)
        mgr._user_path.write_text("User stuff", encoding="utf-8")
        text = mgr.get_display_text()
        assert "[用户级]" in text
        assert "User stuff" in text

    def test_write_memories_splits_correctly(self, tmp_path):
        mgr = MemoryManager(tmp_path)
        content = (
            "### 用户偏好\n"
            "- 使用中文回复\n\n"
            "### 项目知识\n"
            "- 使用Python 3.12\n"
        )
        mgr._write_memories(content)
        user_text = mgr._user_path.read_text(encoding="utf-8")
        project_text = mgr._project_path.read_text(encoding="utf-8")
        assert "用户偏好" in user_text
        assert "项目知识" in project_text


# ──────────────────────────────────────────────
#  TestMemoryExtraction
# ──────────────────────────────────────────────

class TestMemoryExtraction:
    def test_extraction_prompt_contains_categories(self):
        assert "用户偏好" in MEMORY_EXTRACTION_PROMPT
        assert "纠正反馈" in MEMORY_EXTRACTION_PROMPT
        assert "项目知识" in MEMORY_EXTRACTION_PROMPT
        assert "参考资料" in MEMORY_EXTRACTION_PROMPT
        assert "不要重复添加" in MEMORY_EXTRACTION_PROMPT
        assert "不要输出该分类" in MEMORY_EXTRACTION_PROMPT


# ──────────────────────────────────────────────
#  TestConversationInjection
# ──────────────────────────────────────────────

class TestConversationInjection:
    def test_with_env(self):
        conv = ConversationManager()
        conv.inject_environment("env context")
        conv.inject_long_term_memory("instructions", "memories")
        assert conv.ltm_injected is True
        assert any("项目指令" in m.content for m in conv.history)
        assert any("自动记忆" in m.content for m in conv.history)

    def test_idempotent(self):
        conv = ConversationManager()
        conv.inject_long_term_memory("inst", "mem")
        conv.inject_long_term_memory("inst2", "mem2")
        count = sum(1 for m in conv.history if "项目指令" in m.content)
        assert count == 1

    def test_instructions_only(self):
        conv = ConversationManager()
        conv.inject_long_term_memory("my instructions", "")
        assert conv.ltm_injected is True
        assert any("项目指令" in m.content for m in conv.history)

    def test_memories_only(self):
        conv = ConversationManager()
        conv.inject_long_term_memory("", "my memories")
        assert conv.ltm_injected is True
        assert any("自动记忆" in m.content for m in conv.history)

    def test_both_empty(self):
        conv = ConversationManager()
        conv.inject_long_term_memory("", "")
        assert conv.ltm_injected is False

    def test_replace_resets(self):
        conv = ConversationManager()
        conv.inject_long_term_memory("inst", "mem")
        assert conv.ltm_injected is True
        conv.replace_history([])
        assert conv.ltm_injected is False
        assert conv.env_injected is False