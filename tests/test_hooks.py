"""Unit tests for the Hook system (ch12)."""

from __future__ import annotations

import asyncio
import unittest.mock

import pytest

from mewcode.hooks import (
    Action,
    Condition,
    ConditionGroup,
    ConditionParseError,
    Hook,
    HookConfigError,
    HookContext,
    HookEngine,
    LifecycleEvent,
    ToolRejectedError,
    load_hooks,
    parse_condition,
)
from mewcode.hooks.executors import (
    execute_action,
    execute_agent,
    execute_command,
    execute_http,
    execute_prompt,
)


# ──────────────────────────────────────────────
#  TestLifecycleEvent
# ──────────────────────────────────────────────

class TestLifecycleEvent:
    def test_count(self) -> None:
        assert len(LifecycleEvent) == 15

    def test_string_comparison(self) -> None:
        assert LifecycleEvent.session_start == "session_start"
        assert LifecycleEvent.pre_tool_use == "pre_tool_use"

    def test_all_values(self) -> None:
        expected = [
            "session_start", "session_end", "turn_start", "turn_end",
            "pre_tool_use", "post_tool_use", "pre_send", "post_receive",
            "startup", "shutdown", "error", "compact",
            "permission_request", "file_change", "command_execute",
        ]
        assert [e.value for e in LifecycleEvent] == expected


# ──────────────────────────────────────────────
#  TestHookContext
# ──────────────────────────────────────────────

class TestHookContext:
    def test_get_field_tool(self) -> None:
        ctx = HookContext(tool_name="Bash")
        assert ctx.get_field("tool") == "Bash"

    def test_get_field_event(self) -> None:
        ctx = HookContext(event_name="pre_tool_use")
        assert ctx.get_field("event") == "pre_tool_use"

    def test_get_field_args(self) -> None:
        ctx = HookContext(tool_args={"command": "rm -rf /"})
        assert ctx.get_field("args.command") == "rm -rf /"

    def test_get_field_unknown(self) -> None:
        ctx = HookContext()
        assert ctx.get_field("unknown") == ""

    def test_expand_all_variables(self) -> None:
        ctx = HookContext(
            event_name="pre_tool_use",
            tool_name="Bash",
            file_path="/tmp/test.py",
            message="hello",
            error="oops",
            tool_args={"command": "ls"},
        )
        template = "$EVENT $TOOL_NAME $FILE_PATH $MESSAGE $ERROR $TOOL_ARGS.command"
        assert ctx.expand(template) == "pre_tool_use Bash /tmp/test.py hello oops ls"

    def test_expand_undefined_variable_preserved(self) -> None:
        ctx = HookContext()
        assert ctx.expand("$UNKNOWN") == "$UNKNOWN"


# ──────────────────────────────────────────────
#  TestParseCondition
# ──────────────────────────────────────────────

class TestParseCondition:
    def test_single_eq(self) -> None:
        c = parse_condition('tool == "Bash"')
        assert isinstance(c, Condition)
        assert c.field == "tool"
        assert c.operator == "=="
        assert c.value == "Bash"

    def test_single_neq(self) -> None:
        c = parse_condition('tool != "Read"')
        assert isinstance(c, Condition)
        assert c.operator == "!="

    def test_regex(self) -> None:
        c = parse_condition('tool =~ /Bash/')
        assert isinstance(c, Condition)
        assert c.operator == "=~"
        assert c.value == "/Bash/"

    def test_glob(self) -> None:
        c = parse_condition('tool ~= "B*"')
        assert isinstance(c, Condition)
        assert c.operator == "~="

    def test_and_group(self) -> None:
        g = parse_condition('tool == "Bash" && event == "pre_tool_use"')
        assert isinstance(g, ConditionGroup)
        assert g.logic == "and"
        assert len(g.conditions) == 2

    def test_or_group(self) -> None:
        g = parse_condition('tool == "Bash" || tool == "Shell"')
        assert isinstance(g, ConditionGroup)
        assert g.logic == "or"

    def test_mixed_error(self) -> None:
        with pytest.raises(ConditionParseError, match="Cannot mix"):
            parse_condition('tool == "Bash" && tool == "Shell" || event == "x"')

    def test_empty(self) -> None:
        assert parse_condition("") is None
        assert parse_condition("   ") is None

    def test_no_operator(self) -> None:
        c = parse_condition("tool")
        assert isinstance(c, Condition)
        assert c.field == "tool"
        assert c.operator == "=="
        assert c.value == ""


# ──────────────────────────────────────────────
#  TestConditionEvaluate
# ──────────────────────────────────────────────

class TestConditionEvaluate:
    def test_eq(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="==", value="Bash")
        assert c.evaluate(ctx) is True

    def test_neq(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="!=", value="Read")
        assert c.evaluate(ctx) is True

    def test_regex_match(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="=~", value="/Ba/")
        assert c.evaluate(ctx) is True

    def test_regex_no_match(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="=~", value="/Re/")
        assert c.evaluate(ctx) is False

    def test_regex_error(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="=~", value="/[invalid/")
        assert c.evaluate(ctx) is False

    def test_glob_match(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="~=", value="B*")
        assert c.evaluate(ctx) is True

    def test_glob_no_match(self) -> None:
        ctx = HookContext(tool_name="Bash")
        c = Condition(field="tool", operator="~=", value="R*")
        assert c.evaluate(ctx) is False


# ──────────────────────────────────────────────
#  TestConditionGroupEvaluate
# ──────────────────────────────────────────────

class TestConditionGroupEvaluate:
    def test_and_all_pass(self) -> None:
        ctx = HookContext(tool_name="Bash", event_name="pre_tool_use")
        g = ConditionGroup(
            conditions=[
                Condition(field="tool", operator="==", value="Bash"),
                Condition(field="event", operator="==", value="pre_tool_use"),
            ],
            logic="and",
        )
        assert g.evaluate(ctx) is True

    def test_and_partial_fail(self) -> None:
        ctx = HookContext(tool_name="Bash", event_name="post_tool_use")
        g = ConditionGroup(
            conditions=[
                Condition(field="tool", operator="==", value="Bash"),
                Condition(field="event", operator="==", value="pre_tool_use"),
            ],
            logic="and",
        )
        assert g.evaluate(ctx) is False

    def test_or_any_pass(self) -> None:
        ctx = HookContext(tool_name="Bash")
        g = ConditionGroup(
            conditions=[
                Condition(field="tool", operator="==", value="Read"),
                Condition(field="tool", operator="==", value="Bash"),
            ],
            logic="or",
        )
        assert g.evaluate(ctx) is True

    def test_or_all_fail(self) -> None:
        ctx = HookContext(tool_name="Bash")
        g = ConditionGroup(
            conditions=[
                Condition(field="tool", operator="==", value="Read"),
                Condition(field="tool", operator="==", value="Write"),
            ],
            logic="or",
        )
        assert g.evaluate(ctx) is False

    def test_empty_group(self) -> None:
        g = ConditionGroup(conditions=[], logic="and")
        assert g.evaluate(HookContext()) is True


# ──────────────────────────────────────────────
#  TestCommandExecutor
# ──────────────────────────────────────────────

class TestCommandExecutor:
    @pytest.mark.asyncio
    async def test_normal_execution(self) -> None:
        action = Action(type="command", command="echo hello", timeout=5)
        ctx = HookContext()
        result = await execute_command(action, ctx)
        assert result.success is True
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_variable_substitution(self) -> None:
        action = Action(type="command", command="echo $TOOL_NAME", timeout=5)
        ctx = HookContext(tool_name="Bash")
        result = await execute_command(action, ctx)
        assert result.success is True
        assert "Bash" in result.output

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        action = Action(type="command", command="sleep 10", timeout=1)
        ctx = HookContext()
        result = await execute_command(action, ctx)
        assert result.success is False
        assert "timed out" in result.output


# ──────────────────────────────────────────────
#  TestPromptExecutor
# ──────────────────────────────────────────────

class TestPromptExecutor:
    @pytest.mark.asyncio
    async def test_returns_message(self) -> None:
        action = Action(type="prompt", message="blocked")
        ctx = HookContext()
        result = await execute_prompt(action, ctx)
        assert result.success is True
        assert result.output == "blocked"

    @pytest.mark.asyncio
    async def test_variable_expansion(self) -> None:
        action = Action(type="prompt", message="Tool $TOOL_NAME is blocked")
        ctx = HookContext(tool_name="Bash")
        result = await execute_prompt(action, ctx)
        assert result.output == "Tool Bash is blocked"


# ──────────────────────────────────────────────
#  TestHttpExecutor
# ──────────────────────────────────────────────

class TestHttpExecutor:
    @pytest.mark.asyncio
    async def test_mock_request(self) -> None:
        action = Action(
            type="http",
            url="http://example.com/hook",
            method="POST",
            body='{"event":"$EVENT"}',
        )
        ctx = HookContext(event_name="pre_tool_use")

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = unittest.mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = await execute_http(action, ctx)
            assert result.success is True


# ──────────────────────────────────────────────
#  TestAgentExecutor
# ──────────────────────────────────────────────

class TestAgentExecutor:
    @pytest.mark.asyncio
    async def test_stub(self) -> None:
        action = Action(type="agent", prompt="do something")
        ctx = HookContext()
        result = await execute_agent(action, ctx)
        assert result.success is True
        assert "not yet implemented" in result.output


# ──────────────────────────────────────────────
#  TestExecuteAction
# ──────────────────────────────────────────────

class TestExecuteAction:
    @pytest.mark.asyncio
    async def test_dispatch(self) -> None:
        action = Action(type="prompt", message="hi")
        ctx = HookContext()
        result = await execute_action(action, ctx)
        assert result.success is True
        assert result.output == "hi"

    @pytest.mark.asyncio
    async def test_unknown_type(self) -> None:
        action = Action(type="unknown_type")
        ctx = HookContext()
        result = await execute_action(action, ctx)
        assert result.success is False
        assert "Unknown" in result.output


# ──────────────────────────────────────────────
#  TestLoadHooks
# ──────────────────────────────────────────────

class TestLoadHooks:
    def test_complete_config(self) -> None:
        raw = [
            {
                "id": "block-rm",
                "event": "pre_tool_use",
                "if": 'tool == "Bash"',
                "action": {"type": "prompt", "message": "blocked"},
                "reject": True,
            }
        ]
        hooks = load_hooks(raw)
        assert len(hooks) == 1
        assert hooks[0].id == "block-rm"
        assert hooks[0].event == "pre_tool_use"
        assert hooks[0].reject is True

    def test_auto_id(self) -> None:
        raw = [
            {
                "event": "startup",
                "action": {"type": "command", "command": "echo hi"},
            }
        ]
        hooks = load_hooks(raw)
        assert hooks[0].id == "startup_0"

    def test_empty_input(self) -> None:
        assert load_hooks(None) == []
        assert load_hooks([]) == []

    def test_invalid_event(self) -> None:
        raw = [{"event": "invalid_event", "action": {"type": "prompt", "message": "x"}}]
        with pytest.raises(HookConfigError, match="invalid event"):
            load_hooks(raw)

    def test_invalid_action_type(self) -> None:
        raw = [{"event": "startup", "action": {"type": "invalid"}}]
        with pytest.raises(HookConfigError, match="invalid action type"):
            load_hooks(raw)

    def test_missing_required_field(self) -> None:
        raw = [{"event": "startup", "action": {"type": "command"}}]
        with pytest.raises(HookConfigError, match="requires 'command' field"):
            load_hooks(raw)

    def test_reject_on_wrong_event(self) -> None:
        raw = [
            {
                "event": "startup",
                "action": {"type": "prompt", "message": "x"},
                "reject": True,
            }
        ]
        with pytest.raises(HookConfigError, match="reject=true"):
            load_hooks(raw)

    def test_async_on_pre_tool_use(self) -> None:
        raw = [
            {
                "event": "pre_tool_use",
                "action": {"type": "prompt", "message": "x"},
                "async": True,
            }
        ]
        with pytest.raises(HookConfigError, match="async=true"):
            load_hooks(raw)

    def test_invalid_timeout(self) -> None:
        raw = [
            {
                "event": "startup",
                "action": {"type": "command", "command": "echo", "timeout": -1},
            }
        ]
        with pytest.raises(HookConfigError, match="timeout"):
            load_hooks(raw)

    def test_invalid_condition(self) -> None:
        raw = [
            {
                "event": "startup",
                "if": 'tool == "Bash" && tool == "Sh" || event == "x"',
                "action": {"type": "prompt", "message": "x"},
            }
        ]
        with pytest.raises(HookConfigError, match="invalid condition"):
            load_hooks(raw)

    def test_http_hook(self) -> None:
        raw = [
            {
                "event": "post_tool_use",
                "action": {
                    "type": "http",
                    "url": "http://example.com",
                    "method": "POST",
                    "body": '{"key":"val"}',
                },
            }
        ]
        hooks = load_hooks(raw)
        assert len(hooks) == 1
        assert hooks[0].action.type == "http"


# ──────────────────────────────────────────────
#  TestHookEngine
# ──────────────────────────────────────────────

class TestHookEngine:
    @pytest.mark.asyncio
    async def test_find_matching_hooks(self) -> None:
        hooks = [
            Hook(id="h1", event="startup", action=Action(type="prompt", message="hi")),
            Hook(id="h2", event="shutdown", action=Action(type="prompt", message="bye")),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="startup")
        matched = engine.find_matching_hooks("startup", ctx)
        assert len(matched) == 1
        assert matched[0].id == "h1"

    @pytest.mark.asyncio
    async def test_condition_filter(self) -> None:
        hooks = [
            Hook(
                id="h1",
                event="pre_tool_use",
                action=Action(type="prompt", message="blocked"),
                condition=Condition(field="tool", operator="==", value="Bash"),
            ),
        ]
        engine = HookEngine(hooks)

        ctx_bash = HookContext(event_name="pre_tool_use", tool_name="Bash")
        assert len(engine.find_matching_hooks("pre_tool_use", ctx_bash)) == 1

        ctx_read = HookContext(event_name="pre_tool_use", tool_name="Read")
        assert len(engine.find_matching_hooks("pre_tool_use", ctx_read)) == 0

    @pytest.mark.asyncio
    async def test_once_filter(self) -> None:
        hooks = [
            Hook(
                id="h1",
                event="startup",
                action=Action(type="prompt", message="once"),
                once=True,
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="startup")

        matched = engine.find_matching_hooks("startup", ctx)
        assert len(matched) == 1

        hooks[0].mark_executed()
        matched = engine.find_matching_hooks("startup", ctx)
        assert len(matched) == 0

    @pytest.mark.asyncio
    async def test_reject(self) -> None:
        hooks = [
            Hook(
                id="block-rm",
                event="pre_tool_use",
                action=Action(type="prompt", message="dangerous command blocked"),
                condition=Condition(field="tool", operator="==", value="Bash"),
                reject=True,
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="pre_tool_use", tool_name="Bash")
        rejection = await engine.run_pre_tool_hooks(ctx)
        assert rejection is not None
        assert isinstance(rejection, ToolRejectedError)
        assert rejection.tool == "Bash"
        assert "blocked" in rejection.reason

    @pytest.mark.asyncio
    async def test_no_reject(self) -> None:
        hooks = [
            Hook(
                id="log",
                event="pre_tool_use",
                action=Action(type="prompt", message="logging"),
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="pre_tool_use", tool_name="Bash")
        rejection = await engine.run_pre_tool_hooks(ctx)
        assert rejection is None

    @pytest.mark.asyncio
    async def test_prompt_messages(self) -> None:
        hooks = [
            Hook(
                id="inject",
                event="pre_send",
                action=Action(type="prompt", message="extra context"),
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="pre_send")
        await engine.run_hooks("pre_send", ctx)
        msgs = engine.get_prompt_messages()
        assert msgs == ["extra context"]
        assert engine.get_prompt_messages() == []

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self) -> None:
        hooks = [
            Hook(
                id="bad",
                event="startup",
                action=Action(type="command", command="nonexistent_cmd_xyz"),
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="startup")
        await engine.run_hooks("startup", ctx)
        notes = engine.drain_notifications()
        assert len(notes) == 1

    @pytest.mark.asyncio
    async def test_async_hook_does_not_block(self) -> None:
        hooks = [
            Hook(
                id="slow",
                event="startup",
                action=Action(type="command", command="sleep 5", timeout=10),
                async_exec=True,
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="startup")
        await engine.run_hooks("startup", ctx)
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_drain_notifications(self) -> None:
        hooks = [
            Hook(
                id="h1",
                event="startup",
                action=Action(type="prompt", message="hello"),
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="startup")
        await engine.run_hooks("startup", ctx)
        notes = engine.drain_notifications()
        assert len(notes) == 1
        assert notes[0].hook_id == "h1"
        assert notes[0].success is True
        assert engine.drain_notifications() == []


# ──────────────────────────────────────────────
#  TestAgentHookIntegration
# ──────────────────────────────────────────────

class TestAgentHookIntegration:
    @pytest.mark.asyncio
    async def test_pre_tool_use_reject_skips_tool(self) -> None:
        hooks = [
            Hook(
                id="block-rm",
                event="pre_tool_use",
                action=Action(type="prompt", message="blocked"),
                condition=Condition(field="tool", operator="==", value="Bash"),
                reject=True,
            ),
        ]
        engine = HookEngine(hooks)
        ctx = HookContext(event_name="pre_tool_use", tool_name="Bash")
        rejection = await engine.run_pre_tool_hooks(ctx)
        assert rejection is not None
        reason = rejection.reason
        assert "blocked" in reason