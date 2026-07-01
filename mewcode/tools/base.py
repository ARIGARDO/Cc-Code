"""Tool registry and stream event types shared across the codebase."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ──────────────────────────────────────────────
# Stream event types — used by LLMClient.stream()
# ──────────────────────────────────────────────

@dataclass
class TextDelta:
    """A chunk of assistant text (streaming)."""
    text: str


@dataclass
class ThinkingDelta:
    """A chunk of thinking/reasoning text (streaming)."""
    text: str


@dataclass
class ThinkingComplete:
    """Thinking block finished; includes signature for Anthropic."""
    thinking: str
    signature: str


@dataclass
class ToolCallStart:
    """A tool call has been initiated by the model."""
    tool_id: str
    tool_name: str


@dataclass
class ToolCallDelta:
    """Incremental JSON delta for a tool call argument."""
    tool_id: str = ""
    delta: str = ""


@dataclass
class ToolCallComplete:
    """Tool call arguments are complete."""
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class StreamEnd:
    """Stream has ended; carries usage and stop reason."""
    stop_reason: str
    input_tokens: int
    output_tokens: int


StreamEvent = TextDelta | ThinkingDelta | ThinkingComplete | ToolCallStart | ToolCallDelta | ToolCallComplete | StreamEnd


# ──────────────────────────────────────────────
# Tool registry
# ──────────────────────────────────────────────

@dataclass
class ToolParam:
    name: str
    type: str
    description: str
    required: bool = False
    enum: Optional[list[str]] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: list[ToolParam] = field(default_factory=list)

    def to_schema(self, protocol: str = "anthropic") -> dict[str, Any]:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            props[p.name] = prop
            if p.required:
                required.append(p.name)
        schema: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": props,
            },
        }
        if required:
            schema["input_schema"]["required"] = required
        return schema


class ToolRegistry:
    """Central registry for tools available to the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        return [t.to_schema(protocol) for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
