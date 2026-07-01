"""Agent loop: orchestrates LLM calls, tool execution, and event streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator, AsyncGenerator
from dataclasses import dataclass
from typing import Any, Optional

from mewcode.conversation import (
    ConversationManager,
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
#  Agent-event types (emitted to TUI / callers)
# ──────────────────────────────────────────────

@dataclass
class StreamText:
    text: str


@dataclass
class ThinkingText:
    text: str


@dataclass
class ToolUseStart:
    tool_id: str
    tool_name: str


@dataclass
class ToolUseDelta:
    tool_id: str
    delta: str


@dataclass
class ToolUseComplete:
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


AgentEvent = StreamText | ThinkingText | ToolUseStart | ToolUseDelta | ToolUseComplete


# ──────────────────────────────────────────────
#  StreamCollector — consumes LLM stream events
# ──────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    tool_uses: list[ToolUseBlock]
    thinking_blocks: list[ThinkingBlock]
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


class StreamCollector:
    """Collects StreamEvents into an LLMResponse while forwarding AgentEvents."""

    def __init__(self) -> None:
        self.text = ""
        self.tool_uses: list[ToolUseBlock] = []
        self.thinking_blocks: list[ThinkingBlock] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.stop_reason = ""

    async def consume(
        self, stream: AsyncIterator[StreamEvent]
    ) -> AsyncGenerator[AgentEvent, None]:
        pending_tools: dict[str, tuple[str, str]] = {}  # id -> (name, json_accum)

        async for event in stream:
            if isinstance(event, TextDelta):
                self.text += event.text
                yield StreamText(text=event.text)

            elif isinstance(event, ThinkingDelta):
                yield ThinkingText(text=event.text)

            elif isinstance(event, ThinkingComplete):
                self.thinking_blocks.append(
                    ThinkingBlock(thinking=event.thinking, signature=event.signature)
                )
                self.text += event.thinking

            elif isinstance(event, ToolCallStart):
                pending_tools[event.tool_id] = (event.tool_name, "")
                yield ToolUseStart(tool_id=event.tool_id, tool_name=event.tool_name)

            elif isinstance(event, ToolCallDelta):
                if event.tool_id in pending_tools:
                    name, accum = pending_tools[event.tool_id]
                    pending_tools[event.tool_id] = (name, accum + event.delta)
                yield ToolUseDelta(tool_id=event.tool_id, delta=event.delta)

            elif isinstance(event, ToolCallComplete):
                self.tool_uses.append(
                    ToolUseBlock(
                        id=event.tool_id,
                        name=event.tool_name,
                        arguments=event.arguments,
                    )
                )
                yield ToolUseComplete(
                    tool_id=event.tool_id,
                    tool_name=event.tool_name,
                    arguments=event.arguments,
                )

            elif isinstance(event, StreamEnd):
                self.input_tokens = event.input_tokens
                self.output_tokens = event.output_tokens
                self.stop_reason = event.stop_reason

    def response(self) -> LLMResponse:
        return LLMResponse(
            text=self.text,
            tool_uses=self.tool_uses,
            thinking_blocks=self.thinking_blocks,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            stop_reason=self.stop_reason,
        )


# ──────────────────────────────────────────────
#  Agent
# ──────────────────────────────────────────────

class Agent:
    """Orchestrates the LLM ↔ tool loop.

    Consumes an LLMClient + ConversationManager, drives streaming turns,
    and handles tool execution callbacks.
    """

    MAX_TURNS = 50
    MAX_TOKENS_CEILING = 128_000

    def __init__(
        self,
        client: Any,
        conversation: ConversationManager,
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> None:
        self.client = client
        self.conversation = conversation
        self._tools = tools
        self._system = system
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._turn_count = 0

    async def run(self) -> AsyncGenerator[AgentEvent, None]:
        for _ in range(self.MAX_TURNS):
            self._turn_count += 1

            collector = StreamCollector()
            stream = self.client.stream(
                self.conversation, system=self._system, tools=self._tools
            )

            async for agent_event in collector.consume(stream):
                yield agent_event

            response = collector.response()
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            # Write assistant response to history
            self.conversation.add_assistant_message(
                content=response.text,
                tool_uses=response.tool_uses if response.tool_uses else None,
                thinking_blocks=response.thinking_blocks if response.thinking_blocks else None,
            )

            # If no tool calls, we're done
            if not response.tool_uses:
                break

            # Execute tools and add results
            results: list[ToolResultBlock] = []
            for tu in response.tool_uses:
                result = await self._execute_tool(tu)
                results.append(result)

            self.conversation.add_tool_results_message(results)

            # Check for max output tokens → bump ceiling
            if response.stop_reason == "max_tokens":
                current = getattr(self.client, "_max_output_tokens", 8192)
                if hasattr(self.client, "set_max_output_tokens"):
                    new_tokens = min(current * 2, self.MAX_TOKENS_CEILING)
                    self.client.set_max_output_tokens(new_tokens)

    async def _execute_tool(self, tool_use: ToolUseBlock) -> ToolResultBlock:
        import json as _json

        # In a real implementation this dispatches through ToolRegistry.
        # For ch02 we stub it — tools are validated via integration tests.
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            content=_json.dumps({"status": "ok", "args": tool_use.arguments}),
            is_error=False,
        )
