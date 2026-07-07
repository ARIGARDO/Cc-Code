"""Tests for ContentReplacementState (ch08)."""

from __future__ import annotations

from pathlib import Path


from mewcode.conversation import ConversationManager, Message, ToolResultBlock
from mewcode.context.manager import (
    SINGLE_RESULT_CHAR_LIMIT,
    ContentReplacementRecord,
    append_replacement_records,
    apply_tool_result_budget,
    clone_replacement_state,
    create_replacement_state,
    ensure_session_dir,
    load_replacement_records,
    reconstruct_replacement_state,
)


def _make_conv(results: list[tuple[str, str]]) -> ConversationManager:
    conv = ConversationManager()
    conv.add_assistant_message(content="tool call")
    trs = [ToolResultBlock(tool_use_id=tid, content=c) for tid, c in results]
    conv.add_tool_results_message(trs)
    return conv


class TestCreateReturnsEmpty:
    def test(self) -> None:
        s = create_replacement_state()
        assert s.seen_ids == set()
        assert s.replacements == {}


class TestCloneIndependent:
    def test(self) -> None:
        s = create_replacement_state()
        s.seen_ids.add("id1")
        s.replacements["id1"] = "preview"
        c = clone_replacement_state(s)
        assert c.seen_ids == {"id1"}
        assert c.replacements == {"id1": "preview"}
        c.seen_ids.add("id2")
        c.replacements["id2"] = "other"
        assert "id2" not in s.seen_ids
        assert "id2" not in s.replacements


class TestApplyDoesNotMutateConv:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        big = "x" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv = _make_conv([("id1", big)])
        original = conv.history[1].tool_results[0].content
        state = create_replacement_state()
        apply_tool_result_budget(conv, session_dir, state)
        assert conv.history[1].tool_results[0].content == original


class TestFirstCallFreezesUnreplaced:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        conv = _make_conv([("id1", "small")])
        state = create_replacement_state()
        apply_tool_result_budget(conv, session_dir, state)
        assert "id1" in state.seen_ids
        assert "id1" not in state.replacements


class TestReplacementByteIdentical:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        big = "x" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv = _make_conv([("id1", big)])
        state = create_replacement_state()
        api1, _ = apply_tool_result_budget(conv, session_dir, state)
        c1 = api1.history[1].tool_results[0].content
        api2, _ = apply_tool_result_budget(conv, session_dir, state)
        c2 = api2.history[1].tool_results[0].content
        assert c1 == c2


class TestFrozenNeverReplaced:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        conv = _make_conv([("id1", "small")])
        state = create_replacement_state()
        apply_tool_result_budget(conv, session_dir, state)
        assert "id1" in state.seen_ids
        assert "id1" not in state.replacements
        big = "y" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv2 = _make_conv([("id1", "small"), ("id2", big)])
        api_conv, records = apply_tool_result_budget(conv2, session_dir, state)
        tr1 = api_conv.history[1].tool_results[0]
        assert tr1.content == "small"


class TestAggregateOnlyPicksFresh:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        state = create_replacement_state()
        conv = _make_conv([("id1", "a" * 100)])
        apply_tool_result_budget(conv, session_dir, state)
        assert "id1" in state.seen_ids
        assert "id1" not in state.replacements


class TestReconstructFromRecords:
    def test(self) -> None:
        messages = [
            Message(
                role="user",
                tool_results=[ToolResultBlock(tool_use_id="id1", content="x")],
            )
        ]
        records = [ContentReplacementRecord(tool_use_id="id1", replacement="preview")]
        state = reconstruct_replacement_state(messages, records)
        assert state.replacements["id1"] == "preview"


class TestReconstructWithInheritedParent:
    def test(self) -> None:
        messages = [
            Message(
                role="user",
                tool_results=[
                    ToolResultBlock(tool_use_id="id1", content="x"),
                    ToolResultBlock(tool_use_id="id2", content="y"),
                ],
            )
        ]
        records = [ContentReplacementRecord(tool_use_id="id1", replacement="p1")]
        inherited = {"id2": "p2"}
        state = reconstruct_replacement_state(messages, records, inherited_replacements=inherited)
        assert state.replacements["id1"] == "p1"
        assert state.replacements["id2"] == "p2"


class TestAppendAndLoadRecordsRoundtrip:
    def test(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        records = [
            ContentReplacementRecord(tool_use_id="id1", replacement="p1"),
            ContentReplacementRecord(tool_use_id="id2", replacement="p2"),
        ]
        append_replacement_records(session_dir, records)
        loaded = load_replacement_records(session_dir)
        assert len(loaded) == 2
        assert loaded[0].tool_use_id == "id1"
        assert loaded[1].replacement == "p2"