"""MewCode TUI application.

Wires together provider selection, LLM client, Agent, and the Textual UI.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from mewcode.client import (
    AuthenticationError,
    LLMError,
    create_client,
)
from mewcode.config import ProviderConfig
from mewcode.conversation import ConversationManager
from mewcode.agent import Agent


class MewCodeApp:
    """Top-level application that owns the TUI, client, and agent lifecycle."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.client: Any = None
        self.agent: Optional[Agent] = None
        self.conversation = ConversationManager()

    def _select_provider(self) -> None:
        """Choose the first configured provider and create its client."""
        providers = self._config.get("providers", [])
        if not providers:
            self._show_error("No providers configured in config.yaml")
            return

        provider_data = providers[0]
        provider = ProviderConfig(
            name=provider_data.get("name", ""),
            protocol=provider_data.get("protocol", "anthropic"),
            base_url=provider_data.get("base_url"),
            api_key=provider_data.get("api_key", ""),
            model=provider_data.get("model", "claude-sonnet-4-6"),
            thinking=provider_data.get("thinking", True),
        )

        try:
            self.client = create_client(provider)
        except AuthenticationError as e:
            self._show_error(f"Invalid API key: {e}")
            raise

    def _show_error(self, message: str) -> None:
        print(f"[ERROR] {message}")

    async def start(self) -> None:
        self._select_provider()
        if self.client is None:
            return

        self.agent = Agent(
            client=self.client,
            conversation=self.conversation,
            system="You are MewCode, a terminal AI coding assistant.",
            tools=None,
        )

    async def process_message(self, user_input: str) -> None:
        """Send a user message and stream the agent response."""
        if self.agent is None:
            self._show_error("Agent not initialized. Call start() first.")
            return

        self.conversation.add_user_message(user_input)

        try:
            async for event in self.agent.run():
                self._render_event(event)
        except LLMError as e:
            self._show_error(str(e))

    def _render_event(self, event: Any) -> None:
        """Render a single agent event to the terminal (TUI binding point)."""
        from mewcode.agent import StreamText, ThinkingText

        if isinstance(event, StreamText):
            print(event.text, end="", flush=True)
        elif isinstance(event, ThinkingText):
            # In TUI this renders in a dim/spinner panel; for now print dimmed
            print(f"\033[2m{event.text}\033[0m", end="", flush=True)
        # ToolUseStart / ToolUseDelta / ToolUseComplete are rendered
        # by the TUI spinner / tool-status bar — stubbed for ch02.


async def main() -> None:
    """Entry point for ``python -m mewcode``."""
    import yaml
    from pathlib import Path

    config_path = Path("config.yaml")
    config: dict[str, Any] = {"providers": []}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or config

    app = MewCodeApp(config)
    await app.start()

    # Simple REPL loop for ch02 end-to-end verification
    print("MewCode — type a message (Ctrl+C to exit)")
    while True:
        try:
            user_input = input("> ")
            if not user_input.strip():
                continue
            await app.process_message(user_input)
            print()  # newline after response
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break


if __name__ == "__main__":
    asyncio.run(main())
