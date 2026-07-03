"""MewCode TUI application.

Wires together provider selection, LLM client, Agent, ToolRegistry, and the Textual UI.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from mewcode.cache import FileCache
from mewcode.client import (
    AuthenticationError,
    LLMError,
    create_client,
)
from mewcode.config import ProviderConfig
from mewcode.conversation import ConversationManager
from mewcode.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionMode,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)
from mewcode.tools import ToolRegistry, create_default_registry


class MewCodeApp:
    """Top-level application that owns the TUI, client, registry, and agent lifecycle."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.client: Any = None
        self.agent: Optional[Agent] = None
        self.conversation = ConversationManager()
        self.file_cache = FileCache()
        self.registry: ToolRegistry = create_default_registry(file_cache=self.file_cache)
        self._provider: Optional[ProviderConfig] = None

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
        self._provider = provider

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

        protocol = self._provider.protocol if self._provider else "anthropic"

        # Register deferred / system tools
        from mewcode.tools.impl.tool_search import ToolSearchTool
        from mewcode.tools.ask_user import AskUserTool

        self.registry.register(ToolSearchTool(self.registry, protocol=protocol))
        self.registry.register(AskUserTool())

        self.agent = Agent(
            client=self.client,
            registry=self.registry,
            protocol=protocol,
            instructions_content="You are MewCode, a terminal AI coding assistant.",
        )

    def set_plan_mode(self, enabled: bool) -> None:
        """Toggle Plan Mode on/off."""
        if self.agent is None:
            return
        if enabled:
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            self.agent.set_permission_mode(PermissionMode.DEFAULT)

    async def process_message(self, user_input: str) -> None:
        """Send a user message and stream the agent response."""
        if self.agent is None:
            self._show_error("Agent not initialized. Call start() first.")
            return

        self.conversation.add_user_message(user_input)

        try:
            async for event in self.agent.run(self.conversation):
                self._render_event(event)
        except LLMError as e:
            self._show_error(str(e))

    def _render_event(self, event: Any) -> None:
        """Render a single agent event to the terminal (REPL binding point)."""
        if isinstance(event, StreamText):
            print(event.text, end="", flush=True)

        elif isinstance(event, ThinkingText):
            print(f"\033[2m{event.text}\033[0m", end="", flush=True)

        elif isinstance(event, ToolUseEvent):
            print(f"\n[TOOL] {event.tool_name} ...", flush=True)

        elif isinstance(event, ToolResultEvent):
            pass  # Tool results are printed inline by the conversation

        elif isinstance(event, TurnComplete):
            pass  # No visual for turn boundaries

        elif isinstance(event, LoopComplete):
            print()  # Clean newline at end of response

        elif isinstance(event, UsageEvent):
            # Print token usage info
            print(f"\n[USAGE] In: {event.input_tokens} | Out: {event.output_tokens} | Total: {event.total_input}/{event.total_output}", flush=True)

        elif isinstance(event, ErrorEvent):
            print(f"\n[ERROR] {event.message}", flush=True)

        elif isinstance(event, RetryEvent):
            print(f"\n[RETRY] {event.reason}", flush=True)

        elif isinstance(event, CompactNotification):
            print(f"\n[COMPACT] {event.message}", flush=True)

        elif isinstance(event, HookEvent):
            pass  # Hook events not shown in REPL

        elif isinstance(event, PermissionRequest):
            # Auto-allow in REPL mode (no interactive UI)
            event.future.set_result(PermissionResponse.ALLOW)

    @property
    def pending_ask_user_event(self) -> Any:
        """Expose AskUserTool's pending event for TUI consumption."""
        tool = self.registry.get("AskUserQuestion")
        if tool is not None and hasattr(tool, "pending_event"):
            return tool.pending_event
        return None


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