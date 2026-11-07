"""Permission selector widget — inline arrow-key selection.

Mounted into the TUILayout when a permission request is pending.
Avoids push_screen / push_screen_wait to prevent anyio cancel-scope issues.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Static

from cccode.agent import PermissionResponse

_OPTIONS: list[tuple[str, str, PermissionResponse]] = [
    ("1", "Yes", PermissionResponse.ALLOW),
    ("2", "Yes, and don't ask again for this pattern", PermissionResponse.ALLOW_ALWAYS),
    ("3", "No", PermissionResponse.DENY),
]


class PermissionSelector(Static):
    """Inline permission selector with arrow-key navigation.

    When the user presses Enter, the on_confirm callback is called
    with the selected PermissionResponse.
    """

    can_focus = True

    DEFAULT_CSS = """
    PermissionSelector {
        height: auto;
        width: 100%;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
        border-bottom: solid $primary;
    }
    PermissionSelector .perm-title {
        text-style: bold;
        color: $accent;
        padding: 0 0 0 0;
    }
    PermissionSelector .perm-desc {
        color: $text-disabled;
        padding: 0 0 0 2;
    }
    PermissionSelector .perm-opt {
        padding: 0 0 0 2;
        color: $text;
    }
    PermissionSelector .perm-opt.selected {
        color: $text;
        text-style: bold;
        background: $primary 30%;
    }
    PermissionSelector .perm-hint {
        color: $text-disabled;
        padding: 0 0 0 2;
    }
    """

    selected: reactive[int] = reactive(0)

    BINDINGS = [
        Binding("up", "select_prev", "Previous", show=False),
        Binding("down", "select_next", "Next", show=False),
        Binding("enter", "confirm", "Confirm", show=True),
        Binding("1", "quick_0", show=False),
        Binding("2", "quick_1", show=False),
        Binding("3", "quick_2", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        description: str = "",
        on_confirm: Callable[[PermissionResponse], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.description = description
        self._on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        yield Static(f"Permission required: {self.tool_name}", classes="perm-title")
        if self.description:
            yield Static(self.description, classes="perm-desc")
        for i, (key, label, _resp) in enumerate(_OPTIONS):
            prefix = "▸ " if i == 0 else "  "
            yield Static(
                f"{prefix}[{key}] {label}",
                classes="perm-opt selected" if i == 0 else "perm-opt",
                id=f"perm_opt_{i}",
            )
        yield Static("  ↑↓ select   Enter confirm", classes="perm-hint")

    def on_mount(self) -> None:
        self.focus()

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.action_select_prev()
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.action_select_next()
        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_confirm()
        elif event.key in ("1", "2", "3"):
            event.stop()
            event.prevent_default()
            idx = int(event.key) - 1
            self.selected = idx
            self.action_confirm()

    def _refresh_options(self) -> None:
        for i, (key, label, _resp) in enumerate(_OPTIONS):
            try:
                widget = self.query_one(f"#perm_opt_{i}", Static)
            except Exception:
                continue
            prefix = "▸ " if i == self.selected else "  "
            widget.update(f"{prefix}[{key}] {label}")
            if i == self.selected:
                widget.add_class("selected")
            else:
                widget.remove_class("selected")

    def watch_selected(self, _value: int) -> None:
        self._refresh_options()

    def action_select_prev(self) -> None:
        if self.selected > 0:
            self.selected -= 1

    def action_select_next(self) -> None:
        if self.selected < len(_OPTIONS) - 1:
            self.selected += 1

    def action_confirm(self) -> None:
        result = _OPTIONS[self.selected][2]
        if self._on_confirm:
            self._on_confirm(result)

    def action_quick_0(self) -> None:
        self.selected = 0
        self.action_confirm()

    def action_quick_1(self) -> None:
        self.selected = 1
        self.action_confirm()

    def action_quick_2(self) -> None:
        self.selected = 2
        self.action_confirm()