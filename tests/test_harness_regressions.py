"""Regression tests for the Agent execution and permission boundaries."""
import asyncio

import pytest
from pydantic import BaseModel

from cccode.agent import Agent, PermissionRequest, PermissionResponse
from cccode.conversation import ConversationManager
from cccode.hooks import HookEngine
from cccode.permissions.checker import PermissionChecker
from cccode.permissions.dangerous import DangerousCommandDetector
from cccode.permissions.rules import RuleEngine
from cccode.permissions.sandbox import PathSandbox
from cccode.tools import ToolRegistry
from cccode.tools.base import StreamEnd, Tool, ToolCallComplete, ToolResult
from cccode.tools.glob import Glob, Params as GlobParams
from cccode.tools.grep import Grep, Params as GrepParams


class Params(BaseModel):
    file_path: str = ""


class ReadProbe(Tool):
    name = "ReadFile"
    category = "read"
    is_concurrency_safe = True
    params_model = Params

    def __init__(self):
        self.count = 0
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(self, params):
        self.count += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return ToolResult("done")


@pytest.mark.asyncio
async def test_stream_failure_cancels_early_read(tmp_path):
    tool = ReadProbe()
    registry = ToolRegistry()
    registry.register(tool)

    class Client:
        async def stream(self, *args, **kwargs):
            yield ToolCallComplete("read-1", "ReadFile", {})
            await tool.started.wait()
            raise RuntimeError("stream failed")

    agent = Agent(Client(), registry, "anthropic", tmp_path, hook_engine=HookEngine([]))
    conversation = ConversationManager()
    conversation.add_user_message("read")
    with pytest.raises(RuntimeError, match="stream failed"):
        async for _ in agent.run(conversation):
            pass
    assert tool.count == 1
    assert tool.cancelled.is_set()


@pytest.mark.asyncio
async def test_permission_ask_waits_until_stream_end_and_denial_prevents_read(tmp_path):
    tool = ReadProbe()
    registry = ToolRegistry()
    registry.register(tool)
    checker = PermissionChecker(DangerousCommandDetector(), PathSandbox(tmp_path), RuleEngine())
    from cccode.permissions.modes import PermissionMode
    checker.mode = PermissionMode.CUSTOM

    class Client:
        calls = 0
        async def stream(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ToolCallComplete("read-1", "ReadFile", {"file_path": str(tmp_path / "a")})
                await asyncio.sleep(0)
                assert not tool.started.is_set()
                yield StreamEnd("tool_use", 0, 0)
            else:
                yield StreamEnd("end_turn", 0, 0)

    conversation = ConversationManager()
    conversation.add_user_message("read")
    agent = Agent(Client(), registry, "anthropic", tmp_path, permission_checker=checker)
    async for event in agent.run(conversation):
        if isinstance(event, PermissionRequest):
            event.future.set_result(PermissionResponse.DENY)
    assert tool.count == 0
    results = [result for msg in conversation.history for result in msg.tool_results]
    assert len(results) == 1 and results[0].is_error


@pytest.mark.asyncio
async def test_duplicate_call_id_executes_once(tmp_path):
    tool = ReadProbe()
    async def execute(params):
        tool.count += 1
        return ToolResult("ok")
    tool.execute = execute
    registry = ToolRegistry()
    registry.register(tool)

    class Client:
        calls = 0
        async def stream(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ToolCallComplete("same", "ReadFile", {})
                yield ToolCallComplete("same", "ReadFile", {})
                yield StreamEnd("tool_use", 0, 0)
            else:
                yield StreamEnd("end_turn", 0, 0)

    conversation = ConversationManager()
    conversation.add_user_message("read")
    agent = Agent(Client(), registry, "anthropic", tmp_path)
    _ = [event async for event in agent.run(conversation)]
    assert tool.count == 1
    uses = [call for message in conversation.history for call in message.tool_uses]
    results = [result for message in conversation.history for result in message.tool_results]
    assert len(uses) == len(results) == 1


@pytest.mark.asyncio
async def test_search_does_not_follow_file_symlinks_outside_search_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("sensitive-marker", encoding="utf-8")
    (root / "link.txt").symlink_to(secret)
    grep = await Grep().execute(GrepParams(path=str(root), pattern="sensitive-marker"))
    glob = await Glob().execute(GlobParams(path=str(root), pattern="*.txt"))
    escape = await Glob().execute(GlobParams(path=str(root), pattern="../*.txt"))
    assert "sensitive-marker" not in grep.output
    assert "link.txt" not in glob.output
    assert escape.is_error
