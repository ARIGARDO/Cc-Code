"""Tests for RecoveryState (ch08)."""

from __future__ import annotations

import time


from mewcode.context.manager import (
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
    RECOVERY_TOKENS_PER_SKILL,
    RecoveryState,
    build_recovery_attachment,
)


class TestRecoveryAttachmentEmptyWhenNothingRecorded:
    def test(self) -> None:
        state = RecoveryState()
        result = build_recovery_attachment(state, None)
        assert "## 提示" in result


class TestRecoveryAttachmentEmitsAllSections:
    def test(self) -> None:
        state = RecoveryState()
        state.record_file_read("/tmp/a.py", "content_a")
        state.record_skill_invocation("my_skill", "skill_body")
        schemas = [{"name": "ReadFile", "description": "Read a file"}]
        result = build_recovery_attachment(state, schemas)
        assert "## 最近读过的文件" in result
        assert "## 已激活的技能" in result
        assert "## 可用工具" in result
        assert "## 提示" in result


class TestRecoveryFileLimitAndOrder:
    def test(self) -> None:
        state = RecoveryState()
        for i in range(7):
            state.record_file_read(f"/tmp/f{i}.py", f"content_{i}")
            time.sleep(0.01)
        result = build_recovery_attachment(state, None)
        count = result.count("### /tmp/f")
        assert count == RECOVERY_FILE_LIMIT
        assert "/tmp/f6.py" in result
        assert "/tmp/f0.py" not in result


class TestRecoveryTruncatesPerFile:
    def test(self) -> None:
        state = RecoveryState()
        big_content = "x" * int(RECOVERY_TOKENS_PER_FILE * 3.5 + 1000)
        state.record_file_read("/tmp/big.py", big_content)
        result = build_recovery_attachment(state, None)
        assert "内容已截断" in result


class TestRecoverySkillsBudget:
    def test(self) -> None:
        state = RecoveryState()
        big_skill = "s" * int(RECOVERY_TOKENS_PER_SKILL * 3.5 + 100)
        for i in range(20):
            state.record_skill_invocation(f"skill_{i}", big_skill)
            time.sleep(0.01)
        result = build_recovery_attachment(state, None)
        assert "## 已激活的技能" in result