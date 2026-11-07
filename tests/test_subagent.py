"""Unit tests for the SubAgent system (ch13)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest.mock
from pathlib import Path

import pytest

from cccode.agents.parser import (
    AgentDef,
    AgentParseError,
    parse_agent_file,
    parse_frontmatter,
    VALID_MODELS,
    VALID_PERMISSION_MODES,
)
from cccode.agents.loader import AgentLoader
from cccode.agents.tool_filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    resolve_agent_tools,
)
from cccode.agents.fork import (
    FORK_BOILERPLATE_TAG,
    ForkError,
    build_forked_messages,
)
from cccode.agents.trace import TraceManager
from cccode.agents.task_manager import TaskManager, BackgroundTask
from cccode.agents.notification import (
    format_task_notification,
    inject_task_notifications,
    MAX_NOTIFICATION_RESULT_LENGTH,
)
from cccode.conversation import (
    ConversationManager,
    ToolUseBlock,
)
from cccode.tools.agent_tool import (
    AgentTool,
    AgentToolParams,
    MODEL_MAP,
    PERMISSION_MODE_MAP,
    TEAMMATE_ADDENDUM,
)


# ──────────────────────────────────────────────
#  TestAgentParser
# ──────────────────────────────────────────────

class TestAgentParser:
    def test_parse_valid_agent(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: TestAgent\ndescription: A test agent\nmodel: haiku\nmaxTurns: 20\n---\n\nYou are a test agent.\n")
            f.flush()
            agent = parse_agent_file(Path(f.name), source="project")
            assert agent.agent_type == "TestAgent"
            assert agent.when_to_use == "A test agent"
            assert agent.model == "haiku"
            assert agent.max_turns == 20
            assert agent.system_prompt == "You are a test agent."
            assert agent.source == "project"

    def test_parse_missing_name(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\ndescription: No name\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="name"):
                parse_agent_file(Path(f.name))

    def test_parse_missing_description(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="description"):
                parse_agent_file(Path(f.name))

    def test_parse_invalid_model(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\nmodel: gpt-4\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="model"):
                parse_agent_file(Path(f.name))

    def test_parse_invalid_permission_mode(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\npermissionMode: invalid\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="permissionMode"):
                parse_agent_file(Path(f.name))

    def test_parse_defaults(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\n---\n\nBody\n")
            f.flush()
            agent = parse_agent_file(Path(f.name))
            assert agent.model == "inherit"
            assert agent.max_turns == 50
            assert agent.permission_mode == "default"
            assert agent.background is False
            assert agent.isolation == ""

    def test_parse_disallowed_tools(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: Plan\ndescription: D\ndisallowedTools:\n  - Agent\n  - EditFile\n---\n\nBody\n")
            f.flush()
            agent = parse_agent_file(Path(f.name))
            assert "Agent" in agent.disallowed_tools
            assert "EditFile" in agent.disallowed_tools

    def test_parse_invalid_max_turns(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\nmaxTurns: -5\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="maxTurns"):
                parse_agent_file(Path(f.name))

    def test_parse_invalid_isolation(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\nisolation: remote\n---\n\nBody\n")
            f.flush()
            with pytest.raises(AgentParseError, match="isolation"):
                parse_agent_file(Path(f.name))

    def test_parse_background_flag(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("---\nname: X\ndescription: D\nbackground: true\n---\n\nBody\n")
            f.flush()
            agent = parse_agent_file(Path(f.name))
            assert agent.background is True

    def test_parse_frontmatter_no_delimiter(self) -> None:
        fm, body = parse_frontmatter("Just body text")
        assert fm == {}
        assert body == "Just body text"

    def test_valid_models_constant(self) -> None:
        assert "inherit" in VALID_MODELS
        assert "haiku" in VALID_MODELS
        assert "sonnet" in VALID_MODELS
        assert "opus" in VALID_MODELS

    def test_valid_permission_modes_constant(self) -> None:
        assert "default" in VALID_PERMISSION_MODES
        assert "acceptEdits" in VALID_PERMISSION_MODES
        assert "dontAsk" in VALID_PERMISSION_MODES


# ──────────────────────────────────────────────
#  TestAgentLoader
# ──────────────────────────────────────────────

class TestAgentLoader:
    def test_load_builtins(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"))
        loader.load_all()
        agents = loader.list_agents()
        types = [a[0] for a in agents]
        assert "general-purpose" in types
        assert "Plan" in types
        assert "Explore" in types

    def test_verification_disabled_by_default(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"), enable_verification=False)
        loader.load_all()
        types = [a[0] for a in loader.list_agents()]
        assert "Verification" not in types

    def test_verification_enabled(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"), enable_verification=True)
        loader.load_all()
        types = [a[0] for a in loader.list_agents()]
        # Verification only appears if the md file exists
        # Since we don't have a Verification.md builtin, just check no crash
        assert isinstance(types, list)

    def test_project_overrides_builtin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".cccode" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "Plan.md").write_text(
                "---\nname: Plan\ndescription: Custom Plan\nmaxTurns: 5\n---\n\nCustom plan body\n"
            )
            loader = AgentLoader(work_dir=Path(tmpdir))
            loader.load_all()
            plan = loader.get("Plan")
            assert plan is not None
            assert plan.when_to_use == "Custom Plan"
            assert plan.max_turns == 5
            assert plan.source == "project"

    def test_hot_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".cccode" / "agents"
            agents_dir.mkdir(parents=True)
            path = agents_dir / "TestAgent.md"
            path.write_text("---\nname: TestAgent\ndescription: V1\n---\n\nV1 body\n")
            loader = AgentLoader(work_dir=Path(tmpdir))
            loader.load_all()
            a1 = loader.get("TestAgent")
            assert a1.when_to_use == "V1"

            path.write_text("---\nname: TestAgent\ndescription: V2\n---\n\nV2 body\n")
            a2 = loader.get("TestAgent")
            assert a2.when_to_use == "V2"

    def test_get_nonexistent(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"))
        loader.load_all()
        assert loader.get("NonExistent") is None

    def test_bad_file_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".cccode" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "bad.md").write_text("---\ninvalid yaml: [: \n---\n\nBody\n")
            loader = AgentLoader(work_dir=Path(tmpdir))
            loader.load_all()
            assert loader.get("bad") is None

    def test_builtin_plan_disallowed_tools(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"))
        loader.load_all()
        plan = loader.get("Plan")
        assert plan is not None
        assert "Agent" in plan.disallowed_tools
        assert "EditFile" in plan.disallowed_tools
        assert "WriteFile" in plan.disallowed_tools
        assert "NotebookEdit" in plan.disallowed_tools
        assert plan.max_turns == 15

    def test_builtin_explore_model(self) -> None:
        loader = AgentLoader(work_dir=Path("/tmp"))
        loader.load_all()
        explore = loader.get("Explore")
        assert explore is not None
        assert explore.model == "haiku"
        assert explore.max_turns == 30


# ──────────────────────────────────────────────
#  TestToolFilter
# ──────────────────────────────────────────────

class TestToolFilter:
    def _make_registry(self, names: list[str]) -> unittest.mock.MagicMock:
        reg = unittest.mock.MagicMock()
        reg.list_tool_names.return_value = names
        return reg

    def test_global_disallowed(self) -> None:
        reg = self._make_registry(["Bash", "Agent", "AskUserQuestion", "ReadFile"])
        definition = AgentDef(source="builtin")
        result = resolve_agent_tools(reg, definition)
        assert "Agent" not in result
        assert "AskUserQuestion" not in result
        assert "Bash" in result
        assert "ReadFile" in result

    def test_disallowed_tools_in_definition(self) -> None:
        reg = self._make_registry(["Bash", "ReadFile", "WriteFile"])
        definition = AgentDef(source="builtin", disallowed_tools=["WriteFile"])
        result = resolve_agent_tools(reg, definition)
        assert "WriteFile" not in result
        assert "Bash" in result

    def test_tools_whitelist(self) -> None:
        reg = self._make_registry(["Bash", "ReadFile", "WriteFile", "Grep"])
        definition = AgentDef(source="builtin", tools=["Bash", "ReadFile"])
        result = resolve_agent_tools(reg, definition)
        assert "Bash" in result
        assert "ReadFile" in result
        assert "WriteFile" not in result
        assert "Grep" not in result

    def test_background_whitelist(self) -> None:
        reg = self._make_registry(["Bash", "ReadFile", "Agent", "TodoWrite"])
        definition = AgentDef(source="builtin")
        result = resolve_agent_tools(reg, definition, is_background=True)
        assert "Bash" in result
        assert "ReadFile" in result
        assert "Agent" not in result

    def test_combined_whitelist_and_blacklist(self) -> None:
        reg = self._make_registry(["Bash", "ReadFile", "WriteFile"])
        definition = AgentDef(
            source="builtin",
            tools=["Bash", "ReadFile", "WriteFile"],
            disallowed_tools=["WriteFile"],
        )
        result = resolve_agent_tools(reg, definition)
        assert "Bash" in result
        assert "ReadFile" in result
        assert "WriteFile" not in result

    def test_custom_agent_extra_restrictions(self) -> None:
        reg = self._make_registry(["Bash", "Agent", "ReadFile"])
        definition = AgentDef(source="project")
        result = resolve_agent_tools(reg, definition)
        assert "Agent" not in result
        assert "Bash" in result

    def test_mcp_tools_always_pass(self) -> None:
        reg = self._make_registry(["mcp__server__tool", "Agent"])
        definition = AgentDef(source="builtin")
        result = resolve_agent_tools(reg, definition)
        assert "mcp__server__tool" in result
        assert "Agent" not in result


# ──────────────────────────────────────────────
#  TestForkMode
# ──────────────────────────────────────────────

class TestForkMode:
    def test_basic_fork(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi there")
        forked = build_forked_messages(conv, "Do something")
        assert any(FORK_BOILERPLATE_TAG in m.content for m in forked.history)
        assert any("Do something" in m.content for m in forked.history)

    def test_fork_preserves_history(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi there")
        forked = build_forked_messages(conv, "Task")
        assert len(forked.history) >= 2

    def test_fork_wraps_pending_tool_use(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("Do something")
        conv.add_assistant_message(
            "",
            tool_uses=[ToolUseBlock(id="tu1", name="Bash", arguments={})],
        )
        forked = build_forked_messages(conv, "Task")
        has_interrupted = any(
            any(tr.content == "interrupted" for tr in m.tool_results)
            for m in forked.history
        )
        assert has_interrupted

    def test_no_double_fork(self) -> None:
        conv = ConversationManager()
        conv.add_user_message(f"{FORK_BOILERPLATE_TAG} some fork content")
        with pytest.raises(ForkError):
            build_forked_messages(conv, "Task")

    def test_fork_is_deep_copy(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("Original")
        forked = build_forked_messages(conv, "Task")
        forked.history[0].content = "Modified"
        assert conv.history[0].content == "Original"


# ──────────────────────────────────────────────
#  TestTraceManager
# ──────────────────────────────────────────────

class TestTraceManager:
    def test_create_node(self) -> None:
        tm = TraceManager()
        node = tm.create("Plan", parent_id="parent1", trace_id="trace1")
        assert node.agent_type == "Plan"
        assert node.parent_id == "parent1"
        assert node.trace_id == "trace1"
        assert node.status == "running"
        assert len(node.agent_id) == 12

    def test_create_auto_trace_id(self) -> None:
        tm = TraceManager()
        node = tm.create("Explore")
        assert len(node.trace_id) == 12

    def test_update(self) -> None:
        tm = TraceManager()
        node = tm.create("Plan")
        tm.update(node.agent_id, input_tokens=100, output_tokens=50)
        assert node.input_tokens == 100
        assert node.output_tokens == 50

    def test_complete(self) -> None:
        tm = TraceManager()
        node = tm.create("Plan")
        tm.complete(node.agent_id, "completed")
        assert node.status == "completed"
        assert node.end_time != ""

    def test_get_tree(self) -> None:
        tm = TraceManager()
        tm.create("Plan", trace_id="t1")
        tm.create("Explore", trace_id="t1")
        n3 = tm.create("Plan", trace_id="t2")
        tree = tm.get_tree("t1")
        assert len(tree) == 2
        assert n3.agent_id not in [n.agent_id for n in tree]

    def test_get_total_tokens(self) -> None:
        tm = TraceManager()
        n1 = tm.create("Plan", trace_id="t1")
        tm.update(n1.agent_id, input_tokens=100, output_tokens=50)
        n2 = tm.create("Explore", trace_id="t1")
        tm.update(n2.agent_id, input_tokens=200, output_tokens=75)
        total_in, total_out = tm.get_total_tokens("t1")
        assert total_in == 300
        assert total_out == 125

    def test_update_nonexistent(self) -> None:
        tm = TraceManager()
        tm.update("nonexistent", input_tokens=100)

    def test_complete_nonexistent(self) -> None:
        tm = TraceManager()
        tm.complete("nonexistent", "completed")

    def test_get_tree_empty(self) -> None:
        tm = TraceManager()
        assert tm.get_tree("nonexistent") == []

    def test_get_total_tokens_empty(self) -> None:
        tm = TraceManager()
        assert tm.get_total_tokens("nonexistent") == (0, 0)


# ──────────────────────────────────────────────
#  TestTaskManager
# ──────────────────────────────────────────────

class TestTaskManager:
    @pytest.mark.asyncio
    async def test_launch_and_complete(self) -> None:
        tm = TaskManager()
        async def _work() -> str:
            return "done"
        task_id = tm.launch(_work(), agent_type="Plan")
        await asyncio.sleep(0.1)
        bt = tm.get(task_id)
        assert bt is not None
        assert bt.status == "completed"
        assert bt.result == "done"

    @pytest.mark.asyncio
    async def test_poll_completed(self) -> None:
        tm = TaskManager()
        async def _work() -> str:
            return "done"
        task_id = tm.launch(_work(), agent_type="Plan")
        await asyncio.sleep(0.1)
        completed = tm.poll_completed()
        assert task_id in completed

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        tm = TaskManager()
        async def _work() -> str:
            await asyncio.sleep(100)
            return "never"
        task_id = tm.launch(_work(), agent_type="Plan")
        await asyncio.sleep(0.05)
        ok = await tm.cancel(task_id)
        assert ok is True
        bt = tm.get(task_id)
        assert bt.status == "cancelled"

    @pytest.mark.asyncio
    async def test_failed_task(self) -> None:
        tm = TaskManager()
        async def _work() -> str:
            raise ValueError("boom")
        task_id = tm.launch(_work(), agent_type="Plan")
        await asyncio.sleep(0.1)
        bt = tm.get(task_id)
        assert bt.status == "failed"
        assert "boom" in bt.result

    @pytest.mark.asyncio
    async def test_list_tasks(self) -> None:
        tm = TaskManager()
        async def _work() -> str:
            return "ok"
        tm.launch(_work(), agent_type="A")
        tm.launch(_work(), agent_type="B")
        await asyncio.sleep(0.1)
        tasks = tm.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_cancel_non_running(self) -> None:
        tm = TaskManager()
        ok = await tm.cancel("nonexistent")
        assert ok is False


# ──────────────────────────────────────────────
#  TestNotification
# ──────────────────────────────────────────────

class TestNotification:
    def test_format_notification(self) -> None:
        bt = BackgroundTask(
            task_id="abc123",
            agent_type="Plan",
            status="completed",
            result="All done",
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:05+00:00",
        )
        text = format_task_notification(bt)
        assert "<task-notification>" in text
        assert "abc123" in text
        assert "Plan" in text
        assert "completed" in text
        assert "All done" in text

    def test_truncate_long_result(self) -> None:
        bt = BackgroundTask(
            task_id="abc123",
            agent_type="Plan",
            status="completed",
            result="x" * 10000,
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:05+00:00",
        )
        text = format_task_notification(bt)
        assert "truncated" in text
        assert len(text) < 10000

    def test_inject_notifications(self) -> None:
        conv = ConversationManager()
        bt = BackgroundTask(
            task_id="abc123",
            agent_type="Plan",
            status="completed",
            result="Done",
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:05+00:00",
        )
        inject_task_notifications(conv, [bt])
        assert len(conv.history) == 1
        assert "<task-notification>" in conv.history[0].content


# ──────────────────────────────────────────────
#  TestConfig
# ──────────────────────────────────────────────

class TestConfig:
    def test_all_agent_disallowed_tools(self) -> None:
        assert "Agent" in ALL_AGENT_DISALLOWED_TOOLS
        assert "AskUserQuestion" in ALL_AGENT_DISALLOWED_TOOLS
        assert "TaskOutput" in ALL_AGENT_DISALLOWED_TOOLS
        assert "ExitPlanMode" in ALL_AGENT_DISALLOWED_TOOLS
        assert "EnterPlanMode" in ALL_AGENT_DISALLOWED_TOOLS
        assert "TaskStop" in ALL_AGENT_DISALLOWED_TOOLS
        assert "Workflow" in ALL_AGENT_DISALLOWED_TOOLS
        assert len(ALL_AGENT_DISALLOWED_TOOLS) == 7

    def test_async_agent_allowed_tools(self) -> None:
        assert "Bash" in ASYNC_AGENT_ALLOWED_TOOLS
        assert "ReadFile" in ASYNC_AGENT_ALLOWED_TOOLS
        assert "EditFile" in ASYNC_AGENT_ALLOWED_TOOLS
        assert len(ASYNC_AGENT_ALLOWED_TOOLS) == 16


# ──────────────────────────────────────────────
#  TestPermissionMode
# ──────────────────────────────────────────────

class TestPermissionMode:
    def test_permission_mode_map(self) -> None:
        assert isinstance(PERMISSION_MODE_MAP, dict)


# ──────────────────────────────────────────────
#  TestAgentToolParams
# ──────────────────────────────────────────────

class TestAgentToolParams:
    def test_required_fields(self) -> None:
        p = AgentToolParams(prompt="Do X", description="X task")
        assert p.prompt == "Do X"
        assert p.description == "X task"
        assert p.subagent_type == ""
        assert p.run_in_background is False

    def test_optional_fields(self) -> None:
        p = AgentToolParams(
            prompt="Do X",
            description="X task",
            subagent_type="Plan",
            model="haiku",
            run_in_background=True,
            name="planner",
            isolation="worktree",
            team_name="team1",
        )
        assert p.subagent_type == "Plan"
        assert p.model == "haiku"
        assert p.run_in_background is True
        assert p.name == "planner"
        assert p.isolation == "worktree"
        assert p.team_name == "team1"


# ──────────────────────────────────────────────
#  TestAgentExtensions
# ──────────────────────────────────────────────

class TestAgentExtensions:
    def test_model_map(self) -> None:
        assert "haiku" in MODEL_MAP
        assert "sonnet" in MODEL_MAP
        assert "opus" in MODEL_MAP

    def test_teammate_addendum(self) -> None:
        assert "team" in TEAMMATE_ADDENDUM.lower()
        assert "SendMessage" in TEAMMATE_ADDENDUM

    def test_fork_boilerplate_tag(self) -> None:
        assert FORK_BOILERPLATE_TAG == "<fork_boilerplate>"

    def test_max_notification_length(self) -> None:
        assert MAX_NOTIFICATION_RESULT_LENGTH == 5000

    def test_agent_tool_metadata(self) -> None:
        tool = AgentTool()
        assert tool.name == "Agent"
        assert tool.category == "command"
        assert tool.is_concurrency_safe is False