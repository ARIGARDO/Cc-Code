"""Tests for the Slash Command system: parse, registry, complete, handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from cccode.commands.registry import Command, CommandContext, CommandRegistry
from cccode.commands.parser import parse_command, complete
from cccode.commands.handlers import register_all_commands


# ── Helpers ──────────────────────────────────

@dataclass
class MockUI:
    messages: list[str] = None
    sent_messages: list[str] = None
    plan_mode: bool = False

    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if self.sent_messages is None:
            self.sent_messages = []

    def add_system_message(self, msg: str) -> None:
        self.messages.append(msg)

    def send_user_message(self, text: str) -> None:
        self.sent_messages.append(text)

    def set_plan_mode(self, enabled: bool) -> None:
        self.plan_mode = enabled

    def get_token_count(self) -> tuple[int, int]:
        return (0, 0)

    def refresh_status(self) -> None:
        pass


def _make_ctx(
    args: str = "",
    ui: Any = None,
    agent: Any = None,
    conversation: Any = None,
    session: Any = None,
    session_manager: Any = None,
    memory_manager: Any = None,
    config: dict | None = None,
) -> CommandContext:
    return CommandContext(
        args=args,
        agent=agent,
        conversation=conversation,
        session=session,
        session_manager=session_manager,
        memory_manager=memory_manager,
        ui=ui or MockUI(),
        config=config or {},
    )


# ── TestParseCommand ────────────────────────

class TestParseCommand:
    def test_normal(self):
        assert parse_command("/foo bar") == ("foo", "bar", True)

    def test_with_args(self):
        assert parse_command("/compact") == ("compact", "", True)

    def test_case_insensitive(self):
        assert parse_command("/HELP") == ("help", "", True)

    def test_only_slash(self):
        assert parse_command("/") == ("", "", True)

    def test_not_a_command(self):
        assert parse_command("nothing") == ("", "", False)

    def test_empty_input(self):
        assert parse_command("") == ("", "", False)

    def test_whitespace_input(self):
        assert parse_command("   ") == ("", "", False)

    def test_leading_spaces(self):
        assert parse_command("  /foo bar") == ("foo", "bar", True)

    def test_multiple_args(self):
        assert parse_command("/session resume abc123") == ("session", "resume abc123", True)


# ── TestCommandRegistry ─────────────────────

class TestCommandRegistry:
    def test_register_and_find(self):
        reg = CommandRegistry()
        cmd = Command(name="test", description="test cmd", handler=lambda ctx: None)
        reg.register_sync(cmd)
        found = reg.find("test")
        assert found is not None
        assert found.name == "test"

    def test_alias(self):
        reg = CommandRegistry()
        cmd = Command(name="help", description="help", handler=lambda ctx: None, aliases=["h", "?"])
        reg.register_sync(cmd)
        assert reg.find("h").name == "help"
        assert reg.find("?").name == "help"

    def test_name_conflict(self):
        reg = CommandRegistry()
        cmd1 = Command(name="foo", handler=lambda ctx: None)
        cmd2 = Command(name="foo", handler=lambda ctx: None)
        reg.register_sync(cmd1)
        with pytest.raises(ValueError, match="conflicts"):
            reg.register_sync(cmd2)

    def test_alias_conflict(self):
        reg = CommandRegistry()
        cmd1 = Command(name="help", handler=lambda ctx: None, aliases=["h"])
        cmd2 = Command(name="hello", handler=lambda ctx: None, aliases=["h"])
        reg.register_sync(cmd1)
        with pytest.raises(ValueError, match="conflicts"):
            reg.register_sync(cmd2)

    def test_alias_conflicts_with_command_name(self):
        reg = CommandRegistry()
        cmd1 = Command(name="help", handler=lambda ctx: None)
        reg.register_sync(cmd1)
        cmd2 = Command(name="hello", handler=lambda ctx: None, aliases=["help"])
        with pytest.raises(ValueError, match="conflicts"):
            reg.register_sync(cmd2)

    def test_hidden_not_listed(self):
        reg = CommandRegistry()
        cmd = Command(name="secret", handler=lambda ctx: None, hidden=True)
        reg.register_sync(cmd)
        assert reg.list_commands() == []
        assert reg.list_commands(include_hidden=True) == [cmd]

    @pytest.mark.asyncio
    async def test_async_register(self):
        reg = CommandRegistry()
        cmd = Command(name="async_test", handler=lambda ctx: None)
        await reg.register(cmd)
        assert reg.find("async_test") is not None

    def test_find_nonexistent(self):
        reg = CommandRegistry()
        assert reg.find("nope") is None

    @pytest.mark.asyncio
    async def test_unregister(self):
        reg = CommandRegistry()
        cmd = Command(name="temp", handler=lambda ctx: None, aliases=["t"])
        reg.register_sync(cmd)
        result = await reg.unregister("temp")
        assert result is True
        assert reg.find("temp") is None
        assert reg.find("t") is None


# ── TestComplete ────────────────────────────

class TestComplete:
    def _make_registry(self) -> CommandRegistry:
        reg = CommandRegistry()
        register_all_commands(reg)
        return reg

    def test_prefix_match(self):
        reg = self._make_registry()
        results = complete(reg, "/h")
        assert "/help" in results

    def test_alias_match(self):
        reg = self._make_registry()
        results = complete(reg, "/s")
        assert "/status" in results

    def test_no_match(self):
        reg = self._make_registry()
        results = complete(reg, "/zzz")
        assert results == []

    def test_all_commands(self):
        reg = self._make_registry()
        results = complete(reg, "/")
        assert len(results) >= 10

    def test_non_command_prefix(self):
        reg = self._make_registry()
        results = complete(reg, "hello")
        assert results == []


# ── TestHelpHandler ─────────────────────────

class TestHelpHandler:
    @pytest.mark.asyncio
    async def test_help_lists_all(self):
        from cccode.commands.handlers.help import handle_help
        reg = CommandRegistry()
        register_all_commands(reg)
        ui = MockUI()
        ctx = _make_ctx(ui=ui, config={"registry": reg})
        await handle_help(ctx)
        assert len(ui.messages) >= 1
        assert "可用命令" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_help_specific_command(self):
        from cccode.commands.handlers.help import handle_help
        reg = CommandRegistry()
        register_all_commands(reg)
        ui = MockUI()
        ctx = _make_ctx(args="compact", ui=ui, config={"registry": reg})
        await handle_help(ctx)
        assert len(ui.messages) >= 1
        assert "compact" in ui.messages[0]


# ── TestPlanDoHandlers ──────────────────────

class TestPlanDoHandlers:
    @pytest.mark.asyncio
    async def test_plan_mode(self):
        from cccode.commands.handlers.plan import handle_plan
        ui = MockUI()
        ctx = _make_ctx(ui=ui)
        await handle_plan(ctx)
        assert ui.plan_mode is True

    @pytest.mark.asyncio
    async def test_plan_with_args(self):
        from cccode.commands.handlers.plan import handle_plan
        ui = MockUI()
        ctx = _make_ctx(args="设计登录模块", ui=ui)
        await handle_plan(ctx)
        assert ui.plan_mode is True
        assert "设计登录模块" in ui.sent_messages

    @pytest.mark.asyncio
    async def test_do_default(self):
        from cccode.commands.handlers.do import handle_do
        ui = MockUI()
        ctx = _make_ctx(ui=ui)
        await handle_do(ctx)
        assert "Default" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_do_yolo(self):
        from cccode.commands.handlers.do import handle_do
        ui = MockUI()
        mock_agent = MagicMock()
        ctx = _make_ctx(args="yolo", ui=ui, agent=mock_agent)
        await handle_do(ctx)
        assert "Bypass" in ui.messages[0]


# ── TestSkillHandler ────────────────────────

class TestSkillHandler:
    @pytest.mark.asyncio
    async def test_skill_list_no_loader(self):
        from cccode.commands.handlers.skill import handle_skill
        ui = MockUI()
        ctx = _make_ctx(ui=ui)
        await handle_skill(ctx)
        assert any("未初始化" in m for m in ui.messages)

    @pytest.mark.asyncio
    async def test_skill_list_empty(self):
        from cccode.commands.handlers.skill import handle_skill
        ui = MockUI()
        loader = MagicMock()
        loader.list_skills.return_value = []
        ctx = _make_ctx(ui=ui, config={"skill_loader": loader})
        await handle_skill(ctx)
        assert any("没有" in m or "Skill" in m for m in ui.messages)


# ── TestStatusHandler ───────────────────────

class TestStatusHandler:
    @pytest.mark.asyncio
    async def test_status_output(self):
        from cccode.commands.handlers.status import handle_status
        ui = MockUI()
        mock_agent = MagicMock()
        mock_agent.permission_mode = MagicMock()
        mock_agent.permission_mode.value = "default"
        mock_agent.registry.list_tools.return_value = ["tool1", "tool2"]
        ctx = _make_ctx(ui=ui, agent=mock_agent, config={"work_dir": "/tmp"})
        await handle_status(ctx)
        assert any("CcCode 状态" in m for m in ui.messages)


# ── TestSessionHandler ──────────────────────

class TestSessionHandler:
    @pytest.mark.asyncio
    async def test_session_no_manager(self):
        from cccode.commands.handlers.session import handle_session
        ui = MockUI()
        ctx = _make_ctx(ui=ui, session_manager=None)
        await handle_session(ctx)
        assert any("未初始化" in m for m in ui.messages)

    @pytest.mark.asyncio
    async def test_session_list_empty(self):
        from cccode.commands.handlers.session import handle_session
        ui = MockUI()
        mock_mgr = MagicMock()
        mock_mgr.list.return_value = []
        ctx = _make_ctx(ui=ui, session_manager=mock_mgr, args="list")
        await handle_session(ctx)
        assert any("没有" in m for m in ui.messages)


# ── TestMemoryHandler ───────────────────────

class TestMemoryHandler:
    @pytest.mark.asyncio
    async def test_memory_no_manager(self):
        from cccode.commands.handlers.memory import handle_memory
        ui = MockUI()
        ctx = _make_ctx(ui=ui, memory_manager=None)
        await handle_memory(ctx)
        assert any("未初始化" in m for m in ui.messages)

    @pytest.mark.asyncio
    async def test_memory_clear(self):
        from cccode.commands.handlers.memory import handle_memory
        ui = MockUI()
        mock_mgr = MagicMock()
        ctx = _make_ctx(args="clear", ui=ui, memory_manager=mock_mgr)
        await handle_memory(ctx)
        mock_mgr.clear.assert_called_once()
        assert any("清空" in m for m in ui.messages)

    @pytest.mark.asyncio
    async def test_memory_invalid_subcmd(self):
        from cccode.commands.handlers.memory import handle_memory
        ui = MockUI()
        mock_mgr = MagicMock()
        ctx = _make_ctx(args="invalid", ui=ui, memory_manager=mock_mgr)
        await handle_memory(ctx)
        assert any("用法" in m for m in ui.messages)


# ── TestRegisterAllCommands ─────────────────

class TestRegisterAllCommands:
    def test_all_10_commands_registered(self):
        reg = CommandRegistry()
        register_all_commands(reg)
        expected = {"help", "clear", "compact", "plan", "do", "session", "memory", "permission", "status", "skill"}
        actual = {cmd.name for cmd in reg.list_commands(include_hidden=True)}
        assert actual == expected

    def test_no_alias_conflicts(self):
        reg = CommandRegistry()
        register_all_commands(reg)
        assert len(reg.list_commands(include_hidden=True)) == 10

    def test_aliases_work(self):
        reg = CommandRegistry()
        register_all_commands(reg)
        assert reg.find("h").name == "help"
        assert reg.find("?").name == "help"
        assert reg.find("c").name == "compact"
        assert reg.find("p").name == "plan"
        assert reg.find("s").name == "status"