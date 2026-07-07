"""Textual TUI widgets for MewCode.

Provides the visual layout matching the reference design:
  - Header: ASCII cat logo + version + model + workdir
  - Status bar: MCP connection status
  - Chat output area (scrollable, hidden until content)
  - Input bar at bottom
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static


class MewCodeHeader(Static):
    """Top header showing ASCII cat logo, version, model, and workdir."""

    DEFAULT_CSS = """
    MewCodeHeader {
        height: auto;
        padding: 0 1;
        background: $surface;
        color: $text;
        border-bottom: solid $primary;
    }
    """

    version: reactive[str] = reactive("v0.1.0")
    model_name: reactive[str] = reactive("")
    work_dir: reactive[str] = reactive("")

    def __init__(
        self,
        version: str = "v0.1.0",
        model_name: str = "",
        work_dir: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.version = version
        self.model_name = model_name
        self.work_dir = work_dir or ""

    def _render_logo(self) -> str:
        col1 = [
            " /\\_/\\",
            "( o.o )",
            " > ^ <",
        ]
        col2 = [
            f"MewCode {self.version}",
            self.model_name,
            self.work_dir,
        ]
        col1_width = max(len(s) for s in col1)
        lines = []
        for left, right in zip(col1, col2):
            gap = " " * (col1_width - len(left) + 3)
            lines.append(f"{left}{gap}{right}")
        return "\n".join(lines)

    def watch_version(self, _value: str) -> None:
        self.update(self._render_logo())

    def watch_model_name(self, _value: str) -> None:
        self.update(self._render_logo())

    def watch_work_dir(self, _value: str) -> None:
        self.update(self._render_logo())


class MCPStatus(Static):
    """Status bar showing MCP server connection state."""

    DEFAULT_CSS = """
    MCPStatus {
        height: auto;
        padding: 0 1;
        color: $text;
        background: $surface;
    }
    MCPStatus.connected {
        border: round $success;
        padding: 0 1;
    }
    MCPStatus.connecting {
        color: $warning;
    }
    MCPStatus.error {
        color: $error;
    }
    """

    _state: reactive[str] = reactive("idle")
    message: reactive[str] = reactive("")
    tool_count: reactive[int] = reactive(0)

    def set_connected(self, server_count: int, tool_count: int) -> None:
        self._state = "connected"
        self.tool_count = tool_count
        self.message = f"Connected to {server_count} MCP server(s), {tool_count} tools registered"

    def set_connecting(self) -> None:
        self._state = "connecting"
        self.message = "Connecting to MCP servers..."

    def set_error(self, msg: str) -> None:
        self._state = "error"
        self.message = f"MCP error: {msg}"

    def watch_message(self, value: str) -> None:
        if not value:
            self.update("")
            self.remove_class("connected", "connecting", "error")
            return
        self.update(value)
        self.remove_class("connected", "connecting", "error")
        cls_map = {"connecting": "connecting", "connected": "connected", "error": "error"}
        c = cls_map.get(self._state)
        if c:
            self.add_class(c)


class ChatOutput(Static):
    """Scrollable chat output area for streaming agent responses.

    Initially hidden; becomes visible when first content is appended.
    Grows with content up to available space (Claude Code style).
    Uses Static instead of TextArea to avoid cursor/selection highlight.
    """

    DEFAULT_CSS = """
    ChatOutput {
        display: none;
        height: auto;
        max-height: 1fr;
        width: 100%;
        border: none;
        background: $surface;
        color: $text;
        overflow-y: hidden;
    }
    """

    _has_content: bool = False
    _lines: list[str] = []

    def _ensure_visible(self) -> None:
        if not self._has_content:
            self._has_content = True
            self.styles.display = "block"

    def append_text(self, text: str) -> None:
        self._ensure_visible()
        self._lines.append(text)
        self.update("".join(self._lines))
        self.call_after_refresh(self._scroll_end)

    def append_line(self, text: str = "") -> None:
        self.append_text(text + "\n")

    def clear_output(self) -> None:
        self._lines.clear()
        self.update("")
        self._has_content = False
        self.styles.display = "none"

    async def _scroll_end(self) -> None:
        try:
            self.scroll_to(y=999999, animate=False)
        except Exception:
            pass


class TUILayout(Container):
    """Root layout container organizing header, status, chat."""

    DEFAULT_CSS = """
    TUILayout {
        layout: vertical;
        height: auto;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield MewCodeHeader(id="header")
        yield MCPStatus(id="mcp_status")
        yield ChatOutput(id="chat_output")