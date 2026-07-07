"""Tests for context management (ch08)."""

from __future__ import annotations

from pathlib import Path


from mewcode.conversation import ConversationManager, ToolResultBlock
from mewcode.context.manager import (
    PERSISTED_TAG,
    SESSION_SUBDIR,
    SINGLE_RESULT_CHAR_LIMIT,
    CompactCircuitBreaker,
    apply_tool_result_budget,
    build_compact_messages,
    cleanup_tool_results,
    compute_compact_threshold,
    create_replacement_state,
    ensure_session_dir,
    extract_summary,
    make_persisted_preview,
    persist_tool_result,
    should_auto_compact,
)


# ──────────────────────────────────────────────
#  Session dir tests
# ──────────────────────────────────────────────


class TestSessionDir:
    def test_ensure_session_dir(self, tmp_path: Path) -> None:
        result = ensure_session_dir(tmp_path)
        assert result.exists()
        assert result == tmp_path / SESSION_SUBDIR

    def test_cleanup_tool_results(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        (session_dir / "test.txt").write_text("hello")
        cleanup_tool_results(session_dir)
        assert session_dir.exists()
        assert not (session_dir / "test.txt").exists()


# ──────────────────────────────────────────────
#  Persist + preview tests (T6)
# ──────────────────────────────────────────────


class TestPersistToolResult:
    def test_writes_file(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        content = "x" * 100
        path = persist_tool_result("id1", content, session_dir)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == content

    def test_idempotent(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        persist_tool_result("id2", "first", session_dir)
        persist_tool_result("id2", "second", session_dir)
        assert (session_dir / "id2.txt").read_text() == "first"


class TestMakePersistedPreview:
    def test_format(self) -> None:
        content = "a" * 3000
        file_path = Path("/tmp/test.txt")
        preview = make_persisted_preview(content, file_path)
        assert preview.startswith(PERSISTED_TAG)
        assert str(file_path) in preview
        assert "前 2KB" in preview
        assert preview.endswith("</persisted-output>")


# ──────────────────────────────────────────────
#  Threshold tests (T9)
# ──────────────────────────────────────────────


class TestComputeCompactThreshold:
    def test_200k_auto(self) -> None:
        assert compute_compact_threshold(200_000) == 167_000

    def test_200k_manual(self) -> None:
        assert compute_compact_threshold(200_000, manual=True) == 177_000

    def test_128k(self) -> None:
        assert compute_compact_threshold(128_000) == 95_000


class TestShouldAutoCompact:
    def test_below(self) -> None:
        assert not should_auto_compact(166_999, 200_000)

    def test_at(self) -> None:
        assert should_auto_compact(167_000, 200_000)

    def test_above(self) -> None:
        assert should_auto_compact(180_000, 200_000)


# ──────────────────────────────────────────────
#  Extract summary tests (T10)
# ──────────────────────────────────────────────


class TestExtractSummary:
    def test_with_tags(self) -> None:
        text = "<analysis>thinking</analysis><summary>result</summary>"
        assert extract_summary(text) == "result"

    def test_without_tags(self) -> None:
        text = "just some text"
        assert extract_summary(text) == "just some text"

    def test_partial_tags(self) -> None:
        text = "<summary>only open"
        assert extract_summary(text) == "<summary>only open"


# ──────────────────────────────────────────────
#  Circuit breaker tests (T11)
# ──────────────────────────────────────────────


class TestCompactCircuitBreaker:
    def test_initially_closed(self) -> None:
        b = CompactCircuitBreaker()
        assert not b.is_open()

    def test_opens_after_max_failures(self) -> None:
        b = CompactCircuitBreaker(max_failures=3)
        b.record_failure()
        b.record_failure()
        assert not b.is_open()
        b.record_failure()
        assert b.is_open()

    def test_success_resets(self) -> None:
        b = CompactCircuitBreaker(max_failures=2)
        b.record_failure()
        b.record_success()
        b.record_failure()
        assert not b.is_open()


# ──────────────────────────────────────────────
#  Build compact messages tests (T10)
# ──────────────────────────────────────────────


class TestBuildCompactMessages:
    def test_basic(self) -> None:
        msgs = build_compact_messages("test summary")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert "[摘要]" in msgs[0].content
        assert msgs[1].role == "assistant"

    def test_with_attachment(self) -> None:
        msgs = build_compact_messages("summary", attachment="recovery text")
        assert "---" in msgs[0].content
        assert "recovery text" in msgs[0].content


# ──────────────────────────────────────────────
#  Apply tool result budget tests (T8)
# ──────────────────────────────────────────────


class TestApplyToolResultBudget:
    def _make_conv(self, results: list[tuple[str, str]]) -> ConversationManager:
        conv = ConversationManager()
        conv.add_assistant_message(content="tool call")
        trs = [ToolResultBlock(tool_use_id=tid, content=c) for tid, c in results]
        conv.add_tool_results_message(trs)
        return conv

    def test_small_result_unchanged(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        conv = self._make_conv([("id1", "small")])
        state = create_replacement_state()
        api_conv, records = apply_tool_result_budget(conv, session_dir, state)
        assert len(records) == 0
        tr = api_conv.history[1].tool_results[0]
        assert tr.content == "small"

    def test_large_result_persisted(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        big = "x" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv = self._make_conv([("id1", big)])
        state = create_replacement_state()
        api_conv, records = apply_tool_result_budget(conv, session_dir, state)
        assert len(records) == 1
        tr = api_conv.history[1].tool_results[0]
        assert tr.content.startswith(PERSISTED_TAG)

    def test_does_not_mutate_original(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        big = "x" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv = self._make_conv([("id1", big)])
        original_content = conv.history[1].tool_results[0].content
        state = create_replacement_state()
        apply_tool_result_budget(conv, session_dir, state)
        assert conv.history[1].tool_results[0].content == original_content

    def test_replacement_byte_identical(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(tmp_path)
        big = "x" * (SINGLE_RESULT_CHAR_LIMIT + 100)
        conv = self._make_conv([("id1", big)])
        state = create_replacement_state()
        api_conv1, _ = apply_tool_result_budget(conv, session_dir, state)
        first_content = api_conv1.history[1].tool_results[0].content
        api_conv2, _ = apply_tool_result_budget(conv, session_dir, state)
        second_content = api_conv2.history[1].tool_results[0].content
        assert first_content == second_content