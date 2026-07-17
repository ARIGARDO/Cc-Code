"""Integration tests for Agent, StreamCollector, ConversationManager, and tools."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, AsyncGenerator
from pathlib import Path
from typing import Any, Optional

import pytest

from mewcode.agent import (
    Agent,
    AgentEvent,
    HookEvent,
    LoopComplete,
    StreamCollector,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    partition_tool_calls,
)
from mewcode.client import (
    AuthenticationError,
    LLMClient,
    LLMError,
    NetworkError,
    RateLimitError,
    create_client,
)
from mewcode.config import ProviderConfig
from mewcode.conversation import (
    ConversationManager,
    Message,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from mewcode.tools.base import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)
from mewcode.tools import ToolRegistry, create_default_registry


# ──────────────────────────────────────────────
#  Mock LLMClient
# ──────────────────────────────────────────────

class MockLLMClient(LLMClient):
    """Scriptable LLM client for tests."""

    def __init__(self, responses: Optional[list[list[StreamEvent]]] = None) -> None:
        super().__init__()
        self.responses: list[list[StreamEvent]] = responses or []
        self._cursor = 0
        self.stream_calls: list[tuple[Any, Optional[str], Optional[list[dict[str, Any]]]]] = []

    async def stream(
        self,
        conversation: Any,
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
    ) -> AsyncIterator[StreamEvent]:
        self.stream_calls.append((conversation, system, tools))
        if self._cursor >= len(self.responses):
            yield StreamEnd(stop_reason="end_turn", input_tokens=0, output_tokens=0)
            return
        for event in self.responses[self._cursor]:
            yield event
        self._cursor += 1


# ──────────────────────────────────────────────
#  Error hierarchy tests
# ──────────────────────────────────────────────

class TestErrorHierarchy:
    def test_errors_inherit_from_llmerror(self) -> None:
        assert issubclass(AuthenticationError, LLMError)
        assert issubclass(RateLimitError, LLMError)
        assert issubclass(NetworkError, LLMError)

    def test_rate_limit_error_stores_retry_after(self) -> None:
        e = RateLimitError("too many", retry_after=42.0)
        assert e.retry_after == 42.0

    def test_rate_limit_error_default_retry_after(self) -> None:
        e = RateLimitError("too many")
        assert e.retry_after is None

    def test_llmerror_catch_all(self) -> None:
        caught = []
        for exc in [
            AuthenticationError("bad key"),
            RateLimitError("slow"),
            NetworkError("down"),
            LLMError("generic"),
        ]:
            try:
                raise exc
            except LLMError as e:
                caught.append(type(e).__name__)
        assert len(caught) == 4


# ──────────────────────────────────────────────
#  create_client factory tests
# ──────────────────────────────────────────────

class TestCreateClient:
    def test_anthropic_protocol_no_key(self) -> None:
        config = ProviderConfig(protocol="anthropic", api_key="")
        with pytest.raises(AuthenticationError):
            create_client(config)

    def test_openai_protocol_no_key(self) -> None:
        config = ProviderConfig(protocol="openai", api_key="")
        with pytest.raises(AuthenticationError):
            create_client(config)

    def test_unknown_protocol(self) -> None:
        config = ProviderConfig(protocol="gemini")
        with pytest.raises(ValueError, match="Unknown protocol"):
            create_client(config)


# ──────────────────────────────────────────────
#  StreamCollector tests
# ──────────────────────────────────────────────

class TestStreamCollector:
    @pytest.mark.asyncio
    async def test_collects_text_deltas(self) -> None:
        collector = StreamCollector()

        async def events() -> AsyncGenerator[StreamEvent, None]:
            yield TextDelta(text="Hello ")
            yield TextDelta(text="world")
            yield StreamEnd(stop_reason="end_turn", input_tokens=10, output_tokens=5)

        output: list[AgentEvent] = []
        async for ev in collector.consume(events()):
            output.append(ev)

        assert len(output) == 2
        assert isinstance(output[0], StreamText)
        assert output[1].text == "world"

        resp = collector.response()
        assert resp.text == "Hello world"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5

    @pytest.mark.asyncio
    async def test_collects_tool_use_flow(self) -> None:
        collector = StreamCollector()

        async def events() -> AsyncGenerator[StreamEvent, None]:
            yield ToolCallStart(tool_id="tu_1", tool_name="read_file")
            yield ToolCallDelta(tool_id="tu_1", delta='{"path":')
            yield ToolCallDelta(tool_id="tu_1", delta='"/x"')
            yield ToolCallDelta(tool_id="tu_1", delta="}")
            yield ToolCallComplete(
                tool_id="tu_1", tool_name="read_file", arguments={"path": "/x"}
            )
            yield StreamEnd(stop_reason="tool_use", input_tokens=20, output_tokens=15)

        output: list[AgentEvent] = []
        async for ev in collector.consume(events()):
            output.append(ev)

        assert len(output) == 1
        assert isinstance(output[0], ToolUseEvent)
        assert output[0].tool_name == "read_file"
        assert output[0].arguments == {"path": "/x"}

        resp = collector.response()
        assert len(resp.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_collects_thinking_events(self) -> None:
        collector = StreamCollector()

        async def events() -> AsyncGenerator[StreamEvent, None]:
            yield ThinkingDelta(text="Let me think")
            yield ThinkingDelta(text=" about this")
            yield ThinkingComplete(thinking="Let me think about this", signature="sig_abc")
            yield TextDelta(text="Answer")
            yield StreamEnd(stop_reason="end_turn", input_tokens=5, output_tokens=3)

        async for _ in collector.consume(events()):
            pass

        resp = collector.response()
        assert len(resp.thinking_blocks) == 1
        assert resp.thinking_blocks[0].signature == "sig_abc"
        assert "Let me think about this" in resp.text


# ──────────────────────────────────────────────
#  Agent integration tests
# ──────────────────────────────────────────────

class TestAgentIntegration:
    @pytest.mark.asyncio
    async def test_single_step_tool_call(self) -> None:
        """Agent receives ToolCallComplete, executes tool via registry, returns result."""
        registry = create_default_registry()
        conv = ConversationManager()
        conv.add_user_message("read file x")

        # Find a temp file to read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello\nworld\n")
            tmp_path = f.name

        try:
            mock = MockLLMClient(
                responses=[
                    [
                        ToolCallStart(tool_id="tu_1", tool_name="ReadFile"),
                        ToolCallDelta(tool_id="tu_1", delta='{"file_path":"' + tmp_path + '","offset":0,"limit":10}'),
                        ToolCallComplete(
                            tool_id="tu_1",
                            tool_name="ReadFile",
                            arguments={"file_path": tmp_path, "offset": 0, "limit": 10},
                        ),
                        StreamEnd(stop_reason="tool_use", input_tokens=30, output_tokens=20),
                    ],
                    [
                        TextDelta(text="File contents shown above"),
                        StreamEnd(stop_reason="end_turn", input_tokens=40, output_tokens=10),
                    ],
                ]
            )

            agent = Agent(client=mock, registry=registry, protocol="openai")
            events: list[AgentEvent] = []
            async for ev in agent.run(conv):
                events.append(ev)

            tool_uses = [e for e in events if isinstance(e, ToolUseEvent)]
            assert len(tool_uses) == 1
            assert tool_uses[0].tool_name == "ReadFile"

            text_events = [e for e in events if isinstance(e, StreamText)]
            assert any("File contents" in e.text for e in text_events)

            assert agent.total_input_tokens == 70
            assert agent.total_output_tokens == 30

            msgs = conv.get_messages()
            assert len(msgs) >= 3  # user + assistant(tool) + user(tool_result)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_message_splicing(self) -> None:
        """Verify serialize("anthropic") preserves thinking/tool_use/tool_result fields."""
        conv = ConversationManager()
        conv.inject_environment("ENV: test environment context")
        conv.add_user_message("Please use two tools")

        conv.add_assistant_message(
            content="Let me use tools...",
            tool_uses=[
                ToolUseBlock(id="tu_1", name="read_file", arguments={"path": "a.txt"}),
                ToolUseBlock(id="tu_2", name="search", arguments={"query": "test"}),
            ],
            thinking_blocks=[
                ThinkingBlock(thinking="I need two tools", signature="sig_x"),
            ],
        )

        conv.add_tool_results_message([
            ToolResultBlock(tool_use_id="tu_1", content="content A", is_error=False),
            ToolResultBlock(tool_use_id="tu_2", content="found result", is_error=False),
        ])

        conv.add_assistant_message(content="Done!")

        msgs = conv.serialize("anthropic")
        assert len(msgs) == 5, f"Expected 5 messages, got {len(msgs)}"

        assert msgs[0]["role"] == "user"
        assert "ENV" in str(msgs[0]["content"])

        assert msgs[1]["role"] == "user"

        assert msgs[2]["role"] == "assistant"
        assert isinstance(msgs[2]["content"], list)
        block_types = [b["type"] for b in msgs[2]["content"]]
        assert "thinking" in block_types
        assert block_types.count("tool_use") == 2

        assert msgs[3]["role"] == "user"
        assert isinstance(msgs[3]["content"], list)
        assert msgs[3]["content"][0]["type"] == "tool_result"

        assert msgs[4]["role"] == "assistant"
        assert msgs[4]["content"] == "Done!"

    @pytest.mark.asyncio
    async def test_token_usage_accumulates(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("hello")

        mock = MockLLMClient(
            responses=[
                [
                    TextDelta(text="Hi"),
                    StreamEnd(stop_reason="end_turn", input_tokens=15, output_tokens=5),
                ],
            ]
        )

        registry = create_default_registry()
        agent = Agent(client=mock, registry=registry, protocol="openai")
        async for _ in agent.run(conv):
            pass

        assert agent.total_input_tokens == 15
        assert agent.total_output_tokens == 5

    @pytest.mark.asyncio
    async def test_unknown_tool_error(self) -> None:
        """Agent returns error for unknown tool names."""
        registry = create_default_registry()
        conv = ConversationManager()
        conv.add_user_message("use unknown tool")

        mock = MockLLMClient(
            responses=[
                [
                    ToolCallStart(tool_id="t1", tool_name="nonexistent_tool"),
                    ToolCallDelta(tool_id="t1", delta='{}'),
                    ToolCallComplete(tool_id="t1", tool_name="nonexistent_tool", arguments={}),
                    StreamEnd(stop_reason="tool_use", input_tokens=10, output_tokens=5),
                ],
            ]
        )

        registry = create_default_registry()
        agent = Agent(client=mock, registry=registry, protocol="openai")
        async for _ in agent.run(conv):
            pass

        # The tool result message should contain an error
        msgs = conv.get_messages()
        tool_result_msgs = [m for m in msgs if m.role == "user" and m.tool_results]
        assert len(tool_result_msgs) == 1
        assert "unknown tool" in tool_result_msgs[0].tool_results[0].content.lower()
        assert tool_result_msgs[0].tool_results[0].is_error

    @pytest.mark.asyncio
    async def test_write_file_through_registry(self) -> None:
        """Agent executes WriteFile tool through the registry."""
        registry = create_default_registry()
        conv = ConversationManager()
        conv.add_user_message("write a file")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp_path = f.name
        Path(tmp_path).unlink()  # Let WriteFile create it

        try:
            mock = MockLLMClient(
                responses=[
                    [
                        ToolCallStart(tool_id="tu_w", tool_name="WriteFile"),
                        ToolCallDelta(tool_id="tu_w", delta='{"file_path":"' + tmp_path + '","content":"test content"}'),
                        ToolCallComplete(
                            tool_id="tu_w",
                            tool_name="WriteFile",
                            arguments={"file_path": tmp_path, "content": "test content"},
                        ),
                        StreamEnd(stop_reason="tool_use", input_tokens=20, output_tokens=15),
                    ],
                    [
                        TextDelta(text="File written"),
                        StreamEnd(stop_reason="end_turn", input_tokens=10, output_tokens=5),
                    ],
                ]
            )

            agent = Agent(client=mock, registry=registry, protocol="openai")
            async for _ in agent.run(conv):
                pass

            assert Path(tmp_path).read_text() == "test content"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_multi_step_autonomous(self) -> None:
        """Agent autonomously writes a file then reads it back in one session."""
        registry = create_default_registry()
        conv = ConversationManager()
        conv.add_user_message("create and read back a file")

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "test.txt")

            mock = MockLLMClient(
                responses=[
                    # Turn 1: write file
                    [
                        ToolCallStart(tool_id="tw", tool_name="WriteFile"),
                        ToolCallDelta(tool_id="tw", delta='{"file_path":"' + file_path + '","content":"hello multi"}'),
                        ToolCallComplete(
                            tool_id="tw",
                            tool_name="WriteFile",
                            arguments={"file_path": file_path, "content": "hello multi"},
                        ),
                        StreamEnd(stop_reason="tool_use", input_tokens=20, output_tokens=15),
                    ],
                    # Turn 2: read file
                    [
                        ToolCallStart(tool_id="tr", tool_name="ReadFile"),
                        ToolCallDelta(tool_id="tr", delta='{"file_path":"' + file_path + '","offset":0,"limit":10}'),
                        ToolCallComplete(
                            tool_id="tr",
                            tool_name="ReadFile",
                            arguments={"file_path": file_path, "offset": 0, "limit": 10},
                        ),
                        StreamEnd(stop_reason="tool_use", input_tokens=15, output_tokens=10),
                    ],
                    # Turn 3: final text
                    [
                        TextDelta(text="All done"),
                        StreamEnd(stop_reason="end_turn", input_tokens=10, output_tokens=5),
                    ],
                ]
            )

            agent = Agent(client=mock, registry=registry, protocol="openai")
            events: list[AgentEvent] = []
            async for ev in agent.run(conv):
                events.append(ev)

            # Should have executed both tools
            tool_uses = [e for e in events if isinstance(e, ToolUseEvent)]
            assert len(tool_uses) == 2
            assert tool_uses[0].tool_name == "WriteFile"
            assert tool_uses[1].tool_name == "ReadFile"

            assert agent.total_input_tokens == 45
            assert agent.total_output_tokens == 30

            # Verify file was actually written
            assert Path(file_path).read_text() == "hello multi"


# ──────────────────────────────────────────────
#  partition_tool_calls tests
# ──────────────────────────────────────────────

class TestPartitionToolCalls:
    def test_safe_tools_batched(self) -> None:
        registry = create_default_registry()
        uses = [
            ToolUseBlock(id="1", name="ReadFile", arguments={"file_path": "a"}),
            ToolUseBlock(id="2", name="Glob", arguments={"pattern": "*.py"}),
            ToolUseBlock(id="3", name="ReadFile", arguments={"file_path": "b"}),
        ]
        batches = partition_tool_calls(uses, registry)
        # All read-only, all concurrency safe → single batch
        assert len(batches) == 1
        assert len(batches[0].calls) == 3

    def test_write_splits_batch(self) -> None:
        registry = create_default_registry()
        uses = [
            ToolUseBlock(id="1", name="ReadFile", arguments={"file_path": "a"}),
            ToolUseBlock(id="2", name="WriteFile", arguments={"file_path": "b", "content": "x"}),
            ToolUseBlock(id="3", name="ReadFile", arguments={"file_path": "c"}),
        ]
        batches = partition_tool_calls(uses, registry)
        # ReadFile (safe) → batch0, WriteFile (not safe) → batch1, ReadFile → batch2
        assert len(batches) == 3
        assert batches[0].calls[0].name == "ReadFile"
        assert batches[1].calls[0].name == "WriteFile"
        assert batches[2].calls[0].name == "ReadFile"

    def test_unknown_tool_not_safe(self) -> None:
        registry = create_default_registry()
        uses = [
            ToolUseBlock(id="1", name="UnknownTool", arguments={}),
            ToolUseBlock(id="2", name="ReadFile", arguments={"file_path": "a"}),
        ]
        batches = partition_tool_calls(uses, registry)
        # Unknown → not safe → first batch is solo UnknownTool
        assert len(batches) == 2
        assert batches[0].calls[0].name == "UnknownTool"
        assert batches[1].calls[0].name == "ReadFile"


# ──────────────────────────────────────────────
#  ConversationManager tests
# ──────────────────────────────────────────────

class TestConversationManager:
    def test_add_user_message(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("hello")
        msgs = conv.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"

    def test_add_system_reminder_wrapping(self) -> None:
        conv = ConversationManager()
        conv.add_system_reminder("use tools")
        msgs = conv.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content.startswith("<system-reminder>")
        assert "use tools" in msgs[0].content

    def test_inject_environment_idempotent(self) -> None:
        conv = ConversationManager()
        conv.inject_environment("ctx1")
        conv.inject_environment("ctx2")
        msgs = conv.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "ctx1"

    def test_inject_long_term_memory_idempotent(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("instructions", "mem1\nmem2")
        conv.inject_long_term_memory("instructions2", "mem3")
        msgs = conv.get_messages()
        instr_count = sum(1 for m in msgs if "项目指令" in m.content)
        assert instr_count == 1
        assert any("instructions" in m.content for m in msgs)

    def test_replace_history(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("old")
        conv.replace_history([Message(role="user", content="new")])
        assert len(conv.get_messages()) == 1
        assert conv.get_messages()[0].content == "new"

    def test_get_messages_returns_copy(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("test")
        msgs = conv.get_messages()
        msgs[0].content = "modified"
        assert conv.get_messages()[0].content == "test"

    def test_serialize_unknown_protocol(self) -> None:
        conv = ConversationManager()
        with pytest.raises(ValueError, match="Unknown serialization protocol"):
            conv.serialize("gemini")

    def test_serialize_openai_with_tool_use(self) -> None:
        conv = ConversationManager()
        conv.add_user_message("run tool")
        conv.add_assistant_message(
            content="",
            tool_uses=[ToolUseBlock(id="tu_1", name="search", arguments={"q": "x"})],
        )
        conv.add_tool_results_message([
            ToolResultBlock(tool_use_id="tu_1", content="result"),
        ])
        conv.add_assistant_message(content="done")

        items = conv.serialize("openai")
        assert len(items) == 4
        types = [i.get("type", i.get("role", "unknown")) for i in items]
        assert types == ["user", "function_call", "function_call_output", "assistant"]


# ──────────────────────────────────────────────
#  Adaptive thinking tests
# ──────────────────────────────────────────────

class TestAdaptiveThinking:
    def test_supports_adaptive_thinking_opus_4_6(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-opus-4-6-20250514") is True

    def test_supports_adaptive_thinking_sonnet_4_6(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-sonnet-4-6-20250514") is True

    def test_supports_adaptive_thinking_sonnet_4_5(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-sonnet-4-5-20251001") is False

    def test_supports_adaptive_thinking_haiku(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-haiku-4-5-20251001") is False


# ──────────────────────────────────────────────
#  Model short-name mapping tests
# ──────────────────────────────────────────────

class TestModelMapping:
    def test_haiku_maps_to_full_id(self) -> None:
        from mewcode.tools.agent_tool import MODEL_MAP
        assert "haiku" in MODEL_MAP
        assert "haiku" in MODEL_MAP["haiku"]

    def test_sonnet_maps_to_full_id(self) -> None:
        from mewcode.tools.agent_tool import MODEL_MAP
        assert "sonnet" in MODEL_MAP
        assert "sonnet" in MODEL_MAP["sonnet"]

    def test_opus_maps_to_full_id(self) -> None:
        from mewcode.tools.agent_tool import MODEL_MAP
        assert "opus" in MODEL_MAP
        assert "opus" in MODEL_MAP["opus"]

    def test_create_client_for_model_returns_client(self) -> None:
        from mewcode.tools.agent_tool import _create_client_for_model
        parent = ProviderConfig(protocol="openai", api_key="sk-test")
        client = _create_client_for_model("haiku", parent)
        assert isinstance(client, LLMClient)


# ──────────────────────────────────────────────
#  Tool-specific tests
# ──────────────────────────────────────────────

class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_existing_file(self) -> None:
        from mewcode.tools.read_file import ReadFile, Params
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            tmp_path = f.name
        try:
            tool = ReadFile()
            result = await tool.execute(Params(file_path=tmp_path))
            assert not result.is_error
            assert "1\tline1" in result.output
            assert "2\tline2" in result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        from mewcode.tools.read_file import ReadFile, Params
        tool = ReadFile()
        result = await tool.execute(Params(file_path="/nonexistent/file.txt"))
        assert result.is_error
        assert "not found" in result.output

    @pytest.mark.asyncio
    async def test_offset_limit(self) -> None:
        from mewcode.tools.read_file import ReadFile, Params
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\nd\ne\n")
            tmp_path = f.name
        try:
            tool = ReadFile()
            result = await tool.execute(Params(file_path=tmp_path, offset=1, limit=2))
            assert not result.is_error
            assert "2\tb" in result.output
            assert "3\tc" in result.output
            assert "1\ta" not in result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_creates_dirs(self) -> None:
        from mewcode.tools.write_file import WriteFile, Params
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "sub" / "nested" / "test.txt")
            tool = WriteFile()
            result = await tool.execute(Params(file_path=file_path, content="hello"))
            assert not result.is_error
            assert Path(file_path).read_text() == "hello"


class TestEditFile:
    @pytest.mark.asyncio
    async def test_unique_replace(self) -> None:
        from mewcode.tools.edit_file import EditFile, Params
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            tmp_path = f.name
        try:
            tool = EditFile()
            result = await tool.execute(
                Params(file_path=tmp_path, old_string="hello", new_string="hi")
            )
            assert not result.is_error
            assert Path(tmp_path).read_text() == "hi world"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        from mewcode.tools.edit_file import EditFile, Params
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc")
            tmp_path = f.name
        try:
            tool = EditFile()
            result = await tool.execute(
                Params(file_path=tmp_path, old_string="xyz", new_string="nope")
            )
            assert result.is_error
            assert "not found" in result.output.lower()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_multiple_matches(self) -> None:
        from mewcode.tools.edit_file import EditFile, Params
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("dup dup")
            tmp_path = f.name
        try:
            tool = EditFile()
            result = await tool.execute(
                Params(file_path=tmp_path, old_string="dup", new_string="single")
            )
            assert result.is_error
            assert "found 2 times" in result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestBash:
    @pytest.mark.asyncio
    async def test_simple_command(self) -> None:
        from mewcode.tools.bash import Bash, Params
        tool = Bash()
        result = await tool.execute(Params(command="echo hello"))
        assert not result.is_error
        assert "STDOUT:" in result.output
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_stderr_is_error(self) -> None:
        from mewcode.tools.bash import Bash, Params
        tool = Bash()
        result = await tool.execute(Params(command="cat /nonexistent_file_xyz"))
        assert result.is_error
        assert "STDERR:" in result.output or "No such file" in result.output


class TestGlob:
    @pytest.mark.asyncio
    async def test_finds_files(self) -> None:
        from mewcode.tools.glob import Glob, Params
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("")
            (Path(tmpdir) / "b.txt").write_text("")
            (Path(tmpdir) / "c.py").write_text("")
            tool = Glob()
            result = await tool.execute(Params(pattern="*.py", path=tmpdir))
            assert not result.is_error
            assert "a.py" in result.output
            assert "c.py" in result.output
            assert "b.txt" not in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self) -> None:
        from mewcode.tools.glob import Glob, Params
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = Glob()
            result = await tool.execute(Params(pattern="*.xyz", path=tmpdir))
            assert not result.is_error
            assert "No files matched" in result.output


class TestGrep:
    @pytest.mark.asyncio
    async def test_finds_pattern(self) -> None:
        from mewcode.tools.grep import Grep, Params
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "f.py").write_text("def foo():\n    pass\n")
            (Path(tmpdir) / "g.py").write_text("x = 1\n")
            tool = Grep()
            result = await tool.execute(Params(pattern="def foo", path=tmpdir))
            assert not result.is_error
            assert "f.py:1:def foo()" in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self) -> None:
        from mewcode.tools.grep import Grep, Params
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "f.py").write_text("x = 1\n")
            tool = Grep()
            result = await tool.execute(Params(pattern="nonexistent_pattern_xyz", path=tmpdir))
            assert not result.is_error
            assert "No matches found" in result.output

    @pytest.mark.asyncio
    async def test_invalid_regex(self) -> None:
        from mewcode.tools.grep import Grep, Params
        tool = Grep()
        result = await tool.execute(Params(pattern="[invalid"))
        assert result.is_error
        assert "invalid regex" in result.output.lower()


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        from mewcode.tools.read_file import ReadFile
        tool = ReadFile()
        registry.register(tool)
        assert registry.get("ReadFile") is tool

    def test_disable_enable(self) -> None:
        registry = ToolRegistry()
        from mewcode.tools.read_file import ReadFile
        registry.register(ReadFile())
        assert registry.is_enabled("ReadFile")
        registry.disable("ReadFile")
        assert not registry.is_enabled("ReadFile")
        assert registry.get("ReadFile") is None  # disabled tools return None
        registry.enable("ReadFile")
        assert registry.get("ReadFile") is not None

    def test_get_all_schemas_anthropic(self) -> None:
        registry = create_default_registry()
        schemas = registry.get_all_schemas("anthropic")
        assert len(schemas) >= 6
        assert all("name" in s for s in schemas)
        assert all("input_schema" in s for s in schemas)

    def test_get_all_schemas_openai(self) -> None:
        registry = create_default_registry()
        schemas = registry.get_all_schemas("openai")
        assert len(schemas) >= 6
        assert all(s["type"] == "function" for s in schemas)
        assert all("parameters" in s for s in schemas)

    def test_deferred_tool_hidden(self) -> None:
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())
        schemas = registry.get_all_schemas("anthropic")
        names = [s["name"] for s in schemas]
        assert "AskUserQuestion" not in names  # deferred, not discovered

    def test_deferred_after_discovery(self) -> None:
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())
        registry.mark_discovered("AskUserQuestion")
        schemas = registry.get_all_schemas("anthropic")
        names = [s["name"] for s in schemas]
        assert "AskUserQuestion" in names

    def test_search_deferred(self) -> None:
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())
        results = registry.search_deferred("ask user")
        assert len(results) >= 1
        assert any(r["name"] == "AskUserQuestion" for r in results)

    def test_find_deferred_by_names(self) -> None:
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())
        results = registry.find_deferred_by_names(["AskUserQuestion"])
        assert len(results) == 1
        assert results[0]["name"] == "AskUserQuestion"

    def test_get_deferred_tool_names(self) -> None:
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())
        names = registry.get_deferred_tool_names()
        assert "AskUserQuestion" in names


class TestToolSearch:
    @pytest.mark.asyncio
    async def test_search_by_name(self) -> None:
        from mewcode.tools.impl.tool_search import ToolSearchTool, ToolSearchParams
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())

        tool = ToolSearchTool(registry)
        result = await tool.execute(ToolSearchParams(query="ask user"))
        assert not result.is_error
        assert "AskUserQuestion" in result.output

    @pytest.mark.asyncio
    async def test_select_by_name(self) -> None:
        from mewcode.tools.impl.tool_search import ToolSearchTool, ToolSearchParams
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())

        tool = ToolSearchTool(registry)
        result = await tool.execute(ToolSearchParams(query="select:AskUserQuestion"))
        assert not result.is_error
        assert "AskUserQuestion" in result.output

    @pytest.mark.asyncio
    async def test_no_match_returns_available(self) -> None:
        from mewcode.tools.impl.tool_search import ToolSearchTool, ToolSearchParams
        registry = create_default_registry()
        from mewcode.tools.ask_user import AskUserTool
        registry.register(AskUserTool())

        tool = ToolSearchTool(registry)
        result = await tool.execute(ToolSearchParams(query="zzz_nonexistent_zzz"))
        assert "No matching deferred tools" in result.output


# ──────────────────────────────────────────────
#  System Prompt tests (ch05)
# ──────────────────────────────────────────────

class TestSystemPrompt:
    def test_build_system_prompt_normal(self) -> None:
        from mewcode.prompts import build_system_prompt
        prompt = build_system_prompt(work_dir="/home/user/project")
        assert "CcCode" in prompt
        assert "plan mode" not in prompt.lower()

    def test_build_system_prompt_with_custom_instructions(self) -> None:
        from mewcode.prompts import build_system_prompt
        prompt = build_system_prompt(
            work_dir="/home/user/project",
            custom_instructions="Always use type hints.",
        )
        assert "Always use type hints." in prompt

    def test_build_system_prompt_with_memory(self) -> None:
        from mewcode.prompts import build_system_prompt
        prompt = build_system_prompt(
            work_dir="/home/user/project",
            memory_section="User prefers pytest over unittest.",
        )
        assert "User prefers pytest over unittest." in prompt

    def test_build_plan_mode_reminder_full(self) -> None:
        from mewcode.prompts import build_plan_mode_reminder
        reminder = build_plan_mode_reminder(
            Path("/tmp/plan.md"), plan_exists=False, iteration=1,
        )
        assert "plan mode" in reminder.lower()
        assert "MUST NOT" in reminder

    def test_build_plan_mode_reminder_sparse(self) -> None:
        from mewcode.prompts import build_plan_mode_reminder
        reminder = build_plan_mode_reminder(
            Path("/tmp/plan.md"), plan_exists=False, iteration=8,
        )
        assert "Plan mode still active" in reminder

    def test_build_environment_context(self) -> None:
        from mewcode.prompts import build_environment_context
        ctx = build_environment_context(work_dir="/home/user/project")
        assert "/home/user/project" in ctx
        assert "Operating system" in ctx
        assert "Current time" in ctx

    def test_environment_section(self) -> None:
        from mewcode.prompts import environment_section
        section = environment_section(work_dir="/home/user/project")
        assert section.priority == 70
        assert section.name == "Environment"
        assert "/home/user/project" in section.content
        assert "Platform" in section.content
        assert "Date" in section.content

    def test_prompt_builder_empty(self) -> None:
        from mewcode.prompts import PromptBuilder
        builder = PromptBuilder()
        assert builder.build() == ""

    def test_prompt_builder_sorts_by_priority(self) -> None:
        from mewcode.prompts import PromptBuilder, PromptSection
        builder = PromptBuilder()
        builder.add(PromptSection(name="B", priority=20, content="second"))
        builder.add(PromptSection(name="A", priority=10, content="first"))
        builder.add(PromptSection(name="C", priority=30, content="third"))
        result = builder.build()
        parts = result.split("\n\n")
        assert parts[0] == "first"
        assert parts[1] == "second"
        assert parts[2] == "third"

    def test_prompt_builder_skips_empty(self) -> None:
        from mewcode.prompts import PromptBuilder, PromptSection
        builder = PromptBuilder()
        builder.add(PromptSection(name="A", priority=10, content=""))
        builder.add(PromptSection(name="B", priority=20, content="  "))
        builder.add(PromptSection(name="C", priority=30, content="real"))
        result = builder.build()
        assert result == "real"

    def test_prompt_builder_chainable(self) -> None:
        from mewcode.prompts import PromptBuilder, PromptSection
        builder = PromptBuilder()
        result = (
            builder
            .add(PromptSection(name="A", priority=10, content="first"))
            .add(PromptSection(name="B", priority=20, content="second"))
            .build()
        )
        assert "first" in result
        assert "second" in result

    def test_prompt_section_key_fragments(self) -> None:
        from mewcode.prompts import build_system_prompt
        prompt = build_system_prompt(work_dir="/home/user/project")
        assert "IMPORTANT: Be careful not to introduce security" in prompt
        assert "<system-reminder>" in prompt
        assert "Only use emojis if the user explicitly requests it" in prompt
        assert "file_path:line_number" in prompt
        assert "Do not use a colon before tool calls" in prompt