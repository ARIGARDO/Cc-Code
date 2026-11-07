"""LLM client abstraction layer.

Provides a unified async streaming interface over Anthropic and OpenAI,
plus a factory function and a typed error hierarchy.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Optional

from cccode.tools.base import (
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
#  Anthropic cache-control helpers (T13)
# ──────────────────────────────────────────────

_EPHEMERAL = {"type": "ephemeral"}


def _mark_last_user_tail_for_cache(messages: list[dict[str, Any]]) -> None:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                m["content"] = [
                    {"type": "text", "text": content, "cache_control": _EPHEMERAL}
                ]
            elif isinstance(content, list):
                for block in reversed(content):
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["cache_control"] = _EPHEMERAL
                        break
            break


def _mark_last_tool_for_cache(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not tools:
        return tools
    result = list(tools)
    last = dict(result[-1])
    last["cache_control"] = _EPHEMERAL
    result[-1] = last
    return result


# ──────────────────────────────────────────────
#  Error hierarchy (T3 / checklist lines 24-40)
# ──────────────────────────────────────────────

class LLMError(Exception):
    """Base exception for all LLM-related errors."""


class AuthenticationError(LLMError):
    """Invalid or missing API key."""


class RateLimitError(LLMError):
    """Rate limit exceeded; *retry_after* is in seconds when available."""

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NetworkError(LLMError):
    """Network-level failure (connection drop, DNS, timeout)."""


# ──────────────────────────────────────────────
#  LLMClient ABC (T1 / checklist lines 42-53)
# ──────────────────────────────────────────────

class LLMClient(ABC):
    """Abstract base for an LLM provider client."""

    def __init__(self) -> None:
        self._max_output_tokens: int = 8192

    @abstractmethod
    async def stream(
        self,
        conversation: Any,
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
    ) -> AsyncIterator[StreamEvent]:
        """Yield StreamEvents for a single LLM turn."""
        ...

    def set_max_output_tokens(self, tokens: int) -> None:
        self._max_output_tokens = tokens


# ──────────────────────────────────────────────
#  Adaptive-thinking helper (F4 / checklist 56-63)
# ──────────────────────────────────────────────

def _supports_adaptive_thinking(model: str) -> bool:
    """Return True if *model* is claude-opus-4- or claude-sonnet-4-
    and its minor version >= 6 (e.g. claude-sonnet-4-6-…)."""
    for prefix in ("claude-opus-4-", "claude-sonnet-4-"):
        if model.startswith(prefix):
            suffix = model[len(prefix):]
            if suffix and suffix[0].isdigit() and int(suffix[0]) >= 6:
                return True
    return False


# ══════════════════════════════════════════════
#  AnthropicClient (T4 / checklist lines 65-187)
# ══════════════════════════════════════════════

class AnthropicClient(LLMClient):
    """LLMClient backed by the Anthropic Messages streaming API."""

    def __init__(self, config: Any) -> None:
        super().__init__()
        import anthropic

        self._config = config
        key = config.resolve_api_key()
        if not key:
            raise AuthenticationError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY or configure api_key."
            )
        self._client = anthropic.AsyncAnthropic(
            api_key=key,
            base_url=config.base_url or None,
        )
        self._max_output_tokens = config.get_max_output_tokens()

    async def stream(
        self,
        conversation: Any,
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
    ) -> AsyncIterator[StreamEvent]:
        import anthropic

        messages = conversation.serialize("anthropic")
        _mark_last_user_tail_for_cache(messages)

        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
        }
        if system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": _EPHEMERAL}
            ]
        if tools:
            kwargs["tools"] = _mark_last_tool_for_cache(tools)

        # ── thinking configuration ──────────────────────────
        if self._config.thinking:
            if _supports_adaptive_thinking(self._config.model):
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": 0}
            else:
                budget = max(self._max_output_tokens - 1, 1024)
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

        in_thinking = False
        thinking_text = ""
        thinking_signature = ""

        in_tool = False
        tool_id = ""
        tool_name = ""
        tool_arguments = ""

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "thinking":
                            in_thinking = True
                            thinking_text = ""
                            thinking_signature = ""
                        elif event.content_block.type == "tool_use":
                            in_tool = True
                            tool_id = event.content_block.id
                            tool_name = event.content_block.name
                            tool_arguments = ""
                            yield ToolCallStart(tool_id=tool_id, tool_name=tool_name)

                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield TextDelta(text=event.delta.text)
                        elif event.delta.type == "thinking_delta":
                            thinking_text += event.delta.thinking
                            yield ThinkingDelta(text=event.delta.thinking)
                        elif event.delta.type == "signature_delta":
                            thinking_signature += event.delta.signature
                        elif event.delta.type == "input_json_delta":
                            tool_arguments += event.delta.partial_json
                            yield ToolCallDelta(
                                tool_id=tool_id, delta=event.delta.partial_json
                            )

                    elif event.type == "content_block_stop":
                        if in_thinking:
                            yield ThinkingComplete(
                                thinking=thinking_text, signature=thinking_signature
                            )
                            in_thinking = False
                        elif in_tool:
                            try:
                                args = json.loads(tool_arguments)
                            except json.JSONDecodeError:
                                args = {}
                            yield ToolCallComplete(
                                tool_id=tool_id, tool_name=tool_name, arguments=args
                            )
                            in_tool = False

            final_msg = await stream.get_final_message()
            yield StreamEnd(
                stop_reason=final_msg.stop_reason or "end_turn",
                input_tokens=final_msg.usage.input_tokens,
                output_tokens=final_msg.usage.output_tokens,
            )

        except anthropic.AuthenticationError as e:
            raise AuthenticationError(str(e)) from e
        except anthropic.RateLimitError as e:
            retry_after: Optional[float] = None
            try:
                retry_after = float(e.response.headers["retry-after"])
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
            raise RateLimitError(str(e), retry_after=retry_after) from e
        except anthropic.APIConnectionError as e:
            raise NetworkError(str(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error ({e.status_code}): {e.message}") from e


# ══════════════════════════════════════════════
#  OpenAIClient (T5 / checklist lines 190-293)
# ══════════════════════════════════════════════

class OpenAIClient(LLMClient):
    """LLMClient backed by the OpenAI Responses streaming API."""

    def __init__(self, config: Any) -> None:
        super().__init__()
        import openai

        self._config = config
        key = config.resolve_api_key()
        if not key:
            raise AuthenticationError(
                "No OpenAI API key found. Set OPENAI_API_KEY or configure api_key."
            )
        self._client = openai.AsyncOpenAI(
            api_key=key,
            base_url=config.base_url or None,
        )
        self._max_output_tokens = config.get_max_output_tokens()

    async def stream(
        self,
        conversation: Any,
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
    ) -> AsyncIterator[StreamEvent]:
        import openai

        input_items = conversation.serialize("openai")

        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "input": input_items,
            "stream": True,
        }
        if system:
            create_kwargs["instructions"] = system
        if tools:
            create_kwargs["tools"] = [
                {"type": "function", "name": t["name"], "description": t.get("description", ""),
                 "parameters": t.get("input_schema", t.get("parameters", {}))}
                for t in tools
            ]

        # Track active tool calls; keyed by call_id
        active_tools: dict[str, dict[str, Any]] = {}

        try:
            response_stream = await self._client.responses.create(**create_kwargs)

            async for event in response_stream:
                if event.type == "response.output_text.delta":
                    yield TextDelta(text=event.delta)

                elif event.type == "response.output_item.added":
                    item = event.item
                    if item.type == "function_call":
                        existing = active_tools.get(item.id)
                        if existing is not None and existing.get("tool_name", "") == "":
                            # Delta arrived first — update name and flush buffered deltas
                            existing["tool_name"] = item.name
                            existing["call_id"] = getattr(item, "call_id", None) or item.id
                            if not existing["started"]:
                                existing["started"] = True
                                yield ToolCallStart(
                                    tool_id=existing["call_id"], tool_name=item.name
                                )
                            for d in existing.pop("buffered_deltas", []):
                                yield ToolCallDelta(tool_id=existing["call_id"], delta=d.delta)
                        else:
                            active_tools[item.id] = {
                                "call_id": getattr(item, "call_id", None) or item.id,
                                "tool_name": item.name,
                                "json_accum": "",
                                "started": False,
                            }

                elif event.type == "response.function_call_arguments.delta":
                    call_id = event.item_id
                    entry = active_tools.get(call_id)
                    if entry is None:
                        entry = {
                            "call_id": call_id,
                            "tool_name": "",
                            "json_accum": "",
                            "started": False,
                            "buffered_deltas": [],
                        }
                        active_tools[call_id] = entry

                    delta_event = ToolCallDelta(tool_id=entry["call_id"], delta=event.delta)

                    if entry["tool_name"]:
                        # Name is known — yield immediately
                        if not entry["started"]:
                            entry["started"] = True
                            yield ToolCallStart(
                                tool_id=entry["call_id"], tool_name=entry["tool_name"]
                            )
                        yield delta_event
                    else:
                        # Name unknown — buffer until output_item.added arrives
                        entry["buffered_deltas"].append(delta_event)

                    entry["json_accum"] += event.delta

                elif event.type == "response.function_call_arguments.done":
                    call_id = event.item_id
                    entry = active_tools.pop(call_id, None)
                    if entry is None:
                        continue
                    # Flush buffered deltas and ToolCallStart if name was never received
                    if not entry["started"]:
                        entry["started"] = True
                        yield ToolCallStart(
                            tool_id=entry["call_id"],
                            tool_name=entry["tool_name"] or "calling",
                        )
                    for d in entry.pop("buffered_deltas", []):
                        yield d
                    try:
                        args = json.loads(entry["json_accum"])
                    except json.JSONDecodeError:
                        args = {}
                    yield ToolCallComplete(
                        tool_id=entry["call_id"],
                        tool_name=entry["tool_name"] or "calling",
                        arguments=args,
                    )

                elif event.type == "response.completed":
                    resp = event.response
                    usage = getattr(resp, "usage", None)
                    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
                    yield StreamEnd(
                        stop_reason="end_turn",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

        except openai.AuthenticationError as e:
            raise AuthenticationError(str(e)) from e
        except openai.RateLimitError as e:
            retry_after: Optional[float] = None
            try:
                retry_after = float(e.response.headers["retry-after"])
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
            raise RateLimitError(str(e), retry_after=retry_after) from e
        except openai.APIConnectionError as e:
            raise NetworkError(str(e)) from e
        except openai.APIStatusError as e:
            raise LLMError(f"API error ({e.status_code}): {e.message}") from e


# ──────────────────────────────────────────────
#  Factory (F2 / checklist lines 296-301)
# ──────────────────────────────────────────────

def create_client(config: Any) -> LLMClient:
    """Return the correct LLMClient for *config.protocol*."""
    if config.protocol == "anthropic":
        return AnthropicClient(config)
    if config.protocol == "openai":
        return OpenAIClient(config)
    raise ValueError(f"Unknown protocol: {config.protocol}")
