"""Tool ABC, ToolResult, stream events, and shared constants."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

# ──────────────────────────────────────────────
#  Shared constants
# ──────────────────────────────────────────────

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}

MAX_OUTPUT_CHARS = 10000

ToolCategory = Literal["read", "write", "command"]


# ──────────────────────────────────────────────
#  ToolResult
# ──────────────────────────────────────────────

@dataclass
class ToolResult:
    output: str
    is_error: bool = False


# ──────────────────────────────────────────────
#  Tool ABC
# ──────────────────────────────────────────────

class Tool(ABC):
    """Unified base for every tool in the system.

    Subclasses declare class-level metadata and implement ``execute``.
    ``params_model`` is a Pydantic ``BaseModel`` subclass; its
    ``model_json_schema()`` drives automatic schema generation.
    """

    # ── class-level metadata ───────────────────
    name: str = ""
    description: str = ""
    params_model: type[Any] = type(None)  # Pydantic BaseModel
    category: ToolCategory = "read"
    is_concurrency_safe: bool = False
    is_system_tool: bool = False
    should_defer: bool = False

    @property
    def is_read_only(self) -> bool:
        return self.category == "read"

    def get_schema(self) -> dict[str, Any]:
        """Return JSON Schema from Pydantic params model."""
        try:
            raw = self.params_model.model_json_schema()
        except Exception:
            return {"type": "object", "properties": {}}
        # Remove Pydantic noise
        raw.pop("title", None)
        raw.pop("$defs", None)
        return raw

    @abstractmethod
    async def execute(self, params: Any) -> ToolResult:
        """Execute the tool with validated *params*."""
        ...


# ──────────────────────────────────────────────
#  Stream event types — used by LLMClient.stream()
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
