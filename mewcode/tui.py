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
from textual.containers import Container, VerticalScroll
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
    context_info: reactive[str] = reactive("")

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
        if self.context_info:
            col2.append(self.context_info)
        else:
            col2.append("")
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

    def watch_context_info(self, _value: str) -> None:
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


class ChatOutput(VerticalScroll):
    """Scrollable chat output area for streaming agent responses.

    Initially hidden; becomes visible when first content is appended.
    Fills all available vertical space in TUILayout.
    Uses VerticalScroll for proper programmatic scrolling support.
    Contains an inner Static widget for text rendering.

    Auto-scrolls to bottom on new content unless the user has
    manually scrolled up; resumes auto-scroll when scrolled back
    to the bottom.
    """

    DEFAULT_CSS = """
    ChatOutput {
        display: none;
        height: 1fr;
        width: 100%;
        border: none;
        background: $surface;
        color: $text;
        scrollbar-size: 1 1;
        overflow-y: auto;
    }
    ChatOutput > .chat-content {
        height: auto;
        width: 100%;
        background: transparent;
        color: $text;
        padding: 0 1;
    }
    """

    _has_content: bool = False
    _lines: list[str] = []
    _content_widget: Static | None = None
    _auto_scroll: bool = True
    _pending_scroll: bool = False

    def compose(self) -> ComposeResult:
        self._content_widget = Static("", classes="chat-content")
        yield self._content_widget

    def _ensure_visible(self) -> None:
        if not self._has_content:
            self._has_content = True
            self.styles.display = "block"

    def on_scroll(self, event: VerticalScroll.OnScroll) -> None:
        max_y = self.max_scroll_y
        if max_y <= 0:
            return
        at_bottom = self.scroll_y >= max_y - 2
        self._auto_scroll = at_bottom

    def append_text(self, text: str) -> None:
        self._ensure_visible()
        self._lines.append(text)
        if self._content_widget:
            self._content_widget.update("".join(self._lines))
        if self._auto_scroll and not self._pending_scroll:
            self._pending_scroll = True
            self.call_after_refresh(self._schedule_scroll)

    def _schedule_scroll(self) -> None:
        self.set_timer(0.02, self._do_scroll_end)

    def append_line(self, text: str = "") -> None:
        self.append_text(text + "\n")

    def clear_output(self) -> None:
        self._lines.clear()
        if self._content_widget:
            self._content_widget.update("")
        self._has_content = False
        self._auto_scroll = True
        self.styles.display = "none"

    async def _do_scroll_end(self) -> None:
        self._pending_scroll = False
        if not self._auto_scroll:
            return
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass


class TUILayout(Container):
    """Root layout container organizing header, status, chat.

    Uses vertical layout; ChatOutput fills remaining space via 1fr.
    """

    DEFAULT_CSS = """
    TUILayout {
        layout: vertical;
        height: 100%;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield MewCodeHeader(id="header")
        yield MCPStatus(id="mcp_status")
        yield ChatOutput(id="chat_output")