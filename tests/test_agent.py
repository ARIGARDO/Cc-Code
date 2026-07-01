"""Integration tests for Agent, StreamCollector, ConversationManager, and client.

Verifies the ch02 checklist items covering the LLM ↔ Agent ↔ Conversation pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, Optional

import pytest

from mewcode.agent import (
    Agent,
    AgentEvent,
    LLMResponse,
    StreamCollector,
    StreamText,
    ThinkingText,
    ToolUseComplete,
    ToolUseDelta,
    ToolUseStart,
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


# ──────────────────────────────────────────────
#  Mock LLMClient (checklist: test_agent.py:36-56)
# ──────────────────────────────────────────────

class MockLLMClient(LLMClient):
    """Scriptable LLM client for tests.

    *responses* is a list of response-lists; each call to ``stream()``
    consumes the next list.
    """

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
            # Default empty response
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
        """All errors can be caught by ``except LLMError``."""
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
        assert output[0].text == "Hello "
        assert isinstance(output[1], StreamText)
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

        # ToolUseStart + 3x ToolUseDelta + ToolUseComplete = 5 events
        assert len(output) == 5
        assert isinstance(output[0], ToolUseStart)
        assert output[0].tool_name == "read_file"
        assert isinstance(output[-1], ToolUseComplete)
        assert output[-1].arguments == {"path": "/x"}

        resp = collector.response()
        assert len(resp.tool_uses) == 1
        assert resp.tool_uses[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_collects_thinking_events(self) -> None:
        collector = StreamCollector()

        async def events() -> AsyncGenerator[StreamEvent, None]:
            yield ThinkingDelta(text="Let me think")
            yield ThinkingDelta(text=" about this")
            yield ThinkingComplete(thinking="Let me think about this", signature="sig_abc")
            yield TextDelta(text="Answer")
            yield StreamEnd(stop_reason="end_turn", input_tokens=5, output_tokens=3)

        async for ev in collector.consume(events()):
            pass  # consumed silently

        resp = collector.response()
        assert len(resp.thinking_blocks) == 1
        assert resp.thinking_blocks[0].thinking == "Let me think about this"
        assert resp.thinking_blocks[0].signature == "sig_abc"
        assert "Let me think about this" in resp.text


# ──────────────────────────────────────────────
#  Agent integration tests
# ──────────────────────────────────────────────

class TestAgentIntegration:
    @pytest.mark.asyncio
    async def test_single_step_tool_call(self) -> None:
        """Agent receives ToolCallComplete, executes tool, returns result."""
        conv = ConversationManager()
        conv.add_user_message("read file x")

        mock = MockLLMClient(
            responses=[
                [
                    ToolCallStart(tool_id="tu_1", tool_name="read_file"),
                    ToolCallDelta(tool_id="tu_1", delta='{"path":"x"}'),
                    ToolCallComplete(
                        tool_id="tu_1",
                        tool_name="read_file",
                        arguments={"path": "x"},
                    ),
                    StreamEnd(stop_reason="tool_use", input_tokens=30, output_tokens=20),
                ],
                [
                    TextDelta(text="File contents"),
                    StreamEnd(stop_reason="end_turn", input_tokens=40, output_tokens=10),
                ],
            ]
        )

        agent = Agent(client=mock, conversation=conv)
        events: list[AgentEvent] = []
        async for ev in agent.run():
            events.append(ev)

        # Should have tool events from first turn + text from second turn
        tool_starts = [e for e in events if isinstance(e, ToolUseStart)]
        assert len(tool_starts) == 1
        assert tool_starts[0].tool_name == "read_file"

        tool_completes = [e for e in events if isinstance(e, ToolUseComplete)]
        assert len(tool_completes) == 1
        assert tool_completes[0].arguments == {"path": "x"}

        text_events = [e for e in events if isinstance(e, StreamText)]
        assert any("File contents" in e.text for e in text_events)

        # Token accumulation
        assert agent.total_input_tokens == 70
        assert agent.total_output_tokens == 30

        # History should contain: user, assistant(tool), user(tool_result), assistant(text)
        msgs = conv.get_messages()
        assert len(msgs) == 4

    @pytest.mark.asyncio
    async def test_message_splicing(self) -> None:
        """Verify serialize("anthropic") preserves thinking/tool_use/tool_result fields.

        Produces 5 messages: env_context + user + assistant(text+2 tool_use)
        + user(2 tool_result) + assistant(final).
        """
        conv = ConversationManager()
        conv.inject_environment("ENV: test environment context")
        conv.add_user_message("Please use two tools")

        # Assistant response with thinking + 2 tool uses
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

        # Tool results
        conv.add_tool_results_message([
            ToolResultBlock(tool_use_id="tu_1", content="content A", is_error=False),
            ToolResultBlock(tool_use_id="tu_2", content="found result", is_error=False),
        ])

        # Final assistant
        conv.add_assistant_message(content="Done!")

        msgs = conv.serialize("anthropic")
        assert len(msgs) == 5, f"Expected 5 messages, got {len(msgs)}: {msgs}"

        # msg[0]: environment context
        assert msgs[0]["role"] == "user"
        assert "ENV" in str(msgs[0]["content"])

        # msg[1]: user message
        assert msgs[1]["role"] == "user"
        assert "two tools" in str(msgs[1]["content"])

        # msg[2]: assistant with text + thinking + 2 tool_uses
        assert msgs[2]["role"] == "assistant"
        assert isinstance(msgs[2]["content"], list)
        blocks = msgs[2]["content"]
        block_types = [b["type"] for b in blocks]
        assert "thinking" in block_types
        assert "text" in block_types
        assert block_types.count("tool_use") == 2

        # msg[3]: user with 2 tool_results
        assert msgs[3]["role"] == "user"
        assert isinstance(msgs[3]["content"], list)
        assert len(msgs[3]["content"]) == 2
        assert msgs[3]["content"][0]["type"] == "tool_result"
        assert msgs[3]["content"][1]["type"] == "tool_result"

        # msg[4]: final assistant
        assert msgs[4]["role"] == "assistant"
        assert msgs[4]["content"] == "Done!"

    @pytest.mark.asyncio
    async def test_token_usage_accumulates(self) -> None:
        """StreamEnd.input_tokens / output_tokens accumulate to agent totals."""
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

        agent = Agent(client=mock, conversation=conv)
        async for _ in agent.run():
            pass

        assert agent.total_input_tokens == 15
        assert agent.total_output_tokens == 5

    @pytest.mark.asyncio
    async def test_multiple_turns_token_accumulation(self) -> None:
        """Tokens accumulate across multiple turns."""
        conv = ConversationManager()
        conv.add_user_message("multi-turn")

        mock = MockLLMClient(
            responses=[
                [
                    ToolCallStart(tool_id="t1", tool_name="tool_a"),
                    ToolCallDelta(tool_id="t1", delta='{}'),
                    ToolCallComplete(tool_id="t1", tool_name="tool_a", arguments={}),
                    StreamEnd(stop_reason="tool_use", input_tokens=10, output_tokens=8),
                ],
                [
                    TextDelta(text="Final"),
                    StreamEnd(stop_reason="end_turn", input_tokens=12, output_tokens=4),
                ],
            ]
        )

        agent = Agent(client=mock, conversation=conv)
        async for _ in agent.run():
            pass

        assert agent.total_input_tokens == 22
        assert agent.total_output_tokens == 12


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
        assert msgs[0].content.endswith("</system-reminder>")
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
        assert len(msgs) == 1
        assert "instructions" in msgs[0].content
        assert "mem1" in msgs[0].content

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
        assert len(items) == 4  # user_msg + function_call + function_call_output + assistant_msg
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

    def test_supports_adaptive_thinking_opus_4_7(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-opus-4-7-2025") is True

    def test_supports_adaptive_thinking_haiku(self) -> None:
        from mewcode.client import _supports_adaptive_thinking
        assert _supports_adaptive_thinking("claude-haiku-4-5-20251001") is False


# ──────────────────────────────────────────────
#  Model short-name mapping tests (T6)
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
