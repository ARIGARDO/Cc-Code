"""Conversation history management and provider-specific serialization.

Two-layer model:
- Internal: list of ``Message`` dataclasses with full structured fields.
- External: provider-native dicts produced by ``serialize(protocol)``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Optional


# ──────────────────────────────────────────────
#  Message dataclasses (F8 / checklist lines 8-34)
# ──────────────────────────────────────────────

@dataclass
class ToolUseBlock:
    """A model-initiated tool call captured in the conversation."""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    """Result returned for a tool call."""
    tool_use_id: str
    content: str = ""
    is_error: bool = False


@dataclass
class ThinkingBlock:
    """Extended-thinking content + signature for replay."""
    thinking: str
    signature: str


@dataclass
class Message:
    """One turn in the conversation history.

    *role* is "user" or "assistant".
    *content* is the plain-text body (may be empty).
    *tool_uses* / *tool_results* / *thinking_blocks* carry structured extras.
    """
    role: str
    content: str = ""
    tool_uses: list[ToolUseBlock] = field(default_factory=list)
    tool_results: list[ToolResultBlock] = field(default_factory=list)
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)


# ──────────────────────────────────────────────
#  ConversationManager (F9 / checklist lines 37-113)
# ──────────────────────────────────────────────

@dataclass
class ConversationManager:
    """Holds the full conversation history with injection tracking."""

    history: list[Message] = field(default_factory=list)
    env_injected: bool = False
    ltm_injected: bool = False
    last_input_tokens: int = 0

    # ── write helpers ─────────────────────────

    def add_user_message(self, content: str) -> None:
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        content: str = "",
        tool_uses: Optional[list[ToolUseBlock]] = None,
        thinking_blocks: Optional[list[ThinkingBlock]] = None,
    ) -> None:
        self.history.append(
            Message(
                role="assistant",
                content=content,
                tool_uses=list(tool_uses) if tool_uses else [],
                thinking_blocks=list(thinking_blocks) if thinking_blocks else [],
            )
        )

    def add_system_reminder(self, content: str) -> None:
        wrapped = f"<system-reminder>\n{content}\n</system-reminder>"
        self.history.append(Message(role="user", content=wrapped))

    def add_tool_results_message(self, results: list[ToolResultBlock]) -> None:
        self.history.append(Message(role="user", tool_results=list(results)))

    def clear(self) -> None:
        self.history.clear()
        self.env_injected = False
        self.ltm_injected = False
        self.last_input_tokens = 0

    # ── injection (F11) ───────────────────────

    def inject_environment(self, context: str) -> None:
        if self.env_injected:
            return
        self.history.insert(0, Message(role="user", content=context))
        self.env_injected = True

    def inject_long_term_memory(self, instructions: str, memories: str) -> None:
        if self.ltm_injected:
            return

        base_pos = 1 if self.env_injected else 0

        parts: list[str] = []
        if instructions.strip():
            parts.append(f"## 项目指令\n{instructions}")
        if memories.strip():
            parts.append(f"## 自动记忆\n{memories}")

        if parts:
            body = "\n\n".join(parts)
            self.history.insert(base_pos, Message(role="user", content=body))
            self.history.insert(base_pos + 1, Message(role="assistant", content="好的，我已了解项目背景和记忆，会优先参考这些信息来回答问题。"))
            self.ltm_injected = True

    def replace_history(self, messages: list[Message]) -> None:
        self.history = list(messages)
        self.env_injected = False
        self.ltm_injected = False

    def get_messages(self) -> list[Message]:
        return copy.deepcopy(self.history)

    # ── serialization (F9 / F10) ──────────────

    def serialize(self, protocol: str) -> list[dict[str, Any]]:
        if protocol == "anthropic":
            return self._serialize_anthropic()
        if protocol == "openai":
            return self._serialize_openai()
        raise ValueError(f"Unknown serialization protocol: {protocol}")

    def _serialize_anthropic(self) -> list[dict[str, Any]]:
        raw: list[dict[str, Any]] = []

        def _is_reminder(msg: dict[str, Any]) -> bool:
            text = ""
            if isinstance(msg.get("content"), str):
                text = msg["content"]
            elif isinstance(msg.get("content"), list):
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "text":
                        text = b.get("text", "")
                        break
            return text.startswith("<system-reminder>")

        for msg in self.history:
            role = msg.role
            blocks: list[dict[str, Any]] = []

            # thinking blocks
            for tb in msg.thinking_blocks:
                blocks.append({
                    "type": "thinking",
                    "thinking": tb.thinking,
                    "signature": tb.signature,
                })

            # text (skip empty text if there are tool_uses or thinking)
            has_structured = bool(msg.tool_uses or msg.thinking_blocks)
            if msg.content or not has_structured:
                blocks.append({"type": "text", "text": msg.content or ""})

            # tool uses
            for tu in msg.tool_uses:
                blocks.append({
                    "type": "tool_use",
                    "id": tu.id,
                    "name": tu.name,
                    "input": tu.arguments,
                })

            content: Any
            if role == "user" and not msg.tool_results:
                # Simple user message: string content or the wrapped reminder
                content = msg.content
            elif role == "user" and msg.tool_results:
                # User message carrying tool results → list of tool_result blocks
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.tool_use_id,
                        "content": tr.content,
                        "is_error": tr.is_error,
                    }
                    for tr in msg.tool_results
                ]
            else:
                # Assistant message with possible structured blocks
                if len(blocks) == 1 and blocks[0]["type"] == "text":
                    content = blocks[0]["text"] or ""
                else:
                    content = blocks

            anthropic_msg: dict[str, Any] = {"role": role, "content": content}
            raw.append(anthropic_msg)

        # Merge consecutive user reminder messages into the previous user message
        merged: list[dict[str, Any]] = []
        for m in raw:
            if (
                m["role"] == "user"
                and merged
                and merged[-1]["role"] == "user"
                and _is_reminder(m)
            ):
                prev = merged[-1]
                new_text = (
                    m["content"]
                    if isinstance(m["content"], str)
                    else ""
                )
                if isinstance(prev["content"], list):
                    prev["content"].append({"type": "text", "text": new_text})
                else:
                    prev["content"] = prev["content"] + "\n" + new_text
            else:
                merged.append(m)

        return merged

    def _serialize_openai(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for msg in self.history:
            if msg.role == "user" and msg.tool_results:
                for tr in msg.tool_results:
                    items.append({
                        "type": "function_call_output",
                        "call_id": tr.tool_use_id,
                        "output": tr.content,
                    })
            elif msg.role == "user":
                items.append({
                    "role": "user",
                    "content": msg.content,
                })
            elif msg.role == "assistant":
                for tu in msg.tool_uses:
                    items.append({
                        "type": "function_call",
                        "name": tu.name,
                        "call_id": tu.id,
                        "arguments": json.dumps(tu.arguments),
                    })
                if msg.content:
                    items.append({
                        "role": "assistant",
                        "content": msg.content,
                    })
        return items
