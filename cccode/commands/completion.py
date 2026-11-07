"""CompletionPopup: Textual widget for slash command tab-completion."""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList


class CompletionPopup(Vertical):
    DEFAULT_CSS = """
    CompletionPopup {
        dock: bottom;
        height: auto;
        max-height: 10;
        width: 40;
        border: solid $primary;
        background: $surface;
        display: none;
        overflow-y: auto;
    }
    CompletionPopup OptionList {
        height: auto;
    }
    """

    class Selected(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._option_list: OptionList | None = None

    def compose(self) -> Any:
        yield OptionList(id="completion_options")

    def on_mount(self) -> None:
        self._option_list = self.query_one("#completion_options", OptionList)

    def show(self, items: list[str]) -> None:
        if not items or self._option_list is None:
            self.hide()
            return
        self._option_list.clear_options()
        for item in items:
            self._option_list.add_option(item)
        self.styles.display = "block"
        self._option_list.focus()

    def hide(self) -> None:
        self.styles.display = "none"

    @property
    def is_visible(self) -> bool:
        return self.styles.display != "none"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option = event.option
        value = str(option.prompt) if hasattr(option, "prompt") else str(option)
        self.post_message(self.Selected(value))
        self.hide()