"""MewCode TUI application.

Wires together provider selection, LLM client, Agent, ToolRegistry, and the Textual UI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from mewcode.cache import FileCache
from mewcode.client import (
    AuthenticationError,
    LLMError,
    create_client,
)
from mewcode.config import MCPServerConfig, ProviderConfig
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
from mewcode.permissions.checker import PermissionChecker
from mewcode.permissions.dangerous import DangerousCommandDetector
from mewcode.permissions.rules import RuleEngine
from mewcode.permissions.sandbox import PathSandbox
from mewcode.tools import ToolRegistry, create_default_registry

_MODE_CYCLE = [
    PermissionMode.DEFAULT,
    PermissionMode.ACCEPT_EDITS,
    PermissionMode.PLAN,
    PermissionMode.BYPASS,
    PermissionMode.CUSTOM,
    PermissionMode.DONT_ASK,
]


class MewCodeApp:
    """Top-level application that owns the TUI, client, registry, and agent lifecycle."""

    def __init__(
        self,
        config: dict[str, Any],
        mcp_servers: Optional[list[MCPServerConfig]] = None,
    ) -> None:
        self._config = config
        self.client: Any = None
        self.agent: Optional[Agent] = None
        self.conversation = ConversationManager()
        self.file_cache = FileCache()
        self.registry: ToolRegistry = create_default_registry(file_cache=self.file_cache)
        self._provider: Optional[ProviderConfig] = None
        self._work_dir: Path = Path.cwd()
        self._permission_checker: Optional[PermissionChecker] = None

        # MCP integration (T9)
        self._mcp_server_configs: list[MCPServerConfig] = list(mcp_servers or [])
        self._mcp_manager: Optional[Any] = None
        self._mcp_init_task: Optional[asyncio.Task[None]] = None
        self._mcp_instructions: str = ""
        self._mcp_reminder_injected: bool = False

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

        # Build permission checker
        work_dir = self._work_dir
        home = Path.home()
        detector = DangerousCommandDetector()
        sandbox = PathSandbox(project_root=work_dir)
        rule_engine = RuleEngine(
            user_rules_path=home / ".mewcode" / "permissions.yaml",
            project_rules_path=work_dir / ".mewcode" / "permissions.yaml",
            local_rules_path=work_dir / ".mewcode" / "permissions.local.yaml",
        )
        self._permission_checker = PermissionChecker(
            detector=detector,
            sandbox=sandbox,
            rule_engine=rule_engine,
            mode=PermissionMode.DEFAULT,
        )

        self.agent = Agent(
            client=self.client,
            registry=self.registry,
            protocol=protocol,
            work_dir=work_dir,
            permission_checker=self._permission_checker,
            instructions_content="You are MewCode, a terminal AI coding assistant.",
        )

        # Kick off MCP server connections asynchronously (T9 / N1)
        if self._mcp_server_configs:
            self._mcp_init_task = asyncio.create_task(self._init_mcp())

    async def _init_mcp(self) -> None:
        """Connect to all configured MCP servers and register their tools."""
        from mewcode.mcp import MCPManager

        self._mcp_manager = MCPManager()
        self._mcp_manager.load_configs(self._mcp_server_configs)
        errors = await self._mcp_manager.register_all_tools(self.registry)

        if errors:
            for err in errors:
                print(f"[MCP] {err}")

        # Build system-reminder instructions listing available MCP tools
        tool_names = [
            name
            for name in self.registry.list_tools()
            if name.startswith("mcp_")
        ]
        if tool_names:
            lines = ["The following MCP tools are available:"]
            for name in tool_names:
                tool = self.registry.get(name)
                desc = tool.description if tool else ""
                lines.append(f"- {name}: {desc}")
            self._mcp_instructions = "\n".join(lines)
            count = len(self._mcp_server_configs) - len(errors)
            print(
                f"[MCP] Connected to {count} MCP server(s), "
                f"{len(tool_names)} tools registered",
                flush=True,
            )

    async def _shutdown_mcp(self) -> None:
        """Cancel the init task and shut down all MCP clients (N6)."""
        if self._mcp_init_task is not None and not self._mcp_init_task.done():
            self._mcp_init_task.cancel()
            try:
                await self._mcp_init_task
            except (asyncio.CancelledError, Exception):
                pass
            self._mcp_init_task = None
        if self._mcp_manager is not None:
            await self._mcp_manager.shutdown()
            self._mcp_manager = None

    def set_plan_mode(self, enabled: bool) -> None:
        """Toggle Plan Mode on/off."""
        if self.agent is None:
            return
        if enabled:
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            self.agent.set_permission_mode(PermissionMode.DEFAULT)

    def action_cycle_mode(self) -> None:
        """Shift+Tab: cycle through permission modes."""
        if self.agent is None:
            return
        current = self.agent.permission_mode
        try:
            idx = _MODE_CYCLE.index(current)
            next_idx = (idx + 1) % len(_MODE_CYCLE)
        except ValueError:
            next_idx = 0
        new_mode = _MODE_CYCLE[next_idx]
        self.agent.set_permission_mode(new_mode)
        if self._permission_checker:
            self._permission_checker.mode = new_mode

    def handle_command(self, text: str) -> bool:
        """Handle slash commands. Returns True if consumed, False if not a command."""
        stripped = text.strip()
        if not stripped.startswith("/"):
            return False

        parts = stripped.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/plan":
            self.set_plan_mode(True)
            print("[MODE] Switched to Plan mode")
            return True

        if cmd == "/do":
            if arg.lower() in ("yolo", "bypass"):
                if self.agent:
                    self.agent.set_permission_mode(PermissionMode.BYPASS)
                    if self._permission_checker:
                        self._permission_checker.mode = PermissionMode.BYPASS
                print("[MODE] Switched to Bypass mode (YOLO)")
            else:
                self.set_plan_mode(False)
                print("[MODE] Switched to Default mode")
            return True

        if cmd in ("/next", "/n"):
            self.action_cycle_mode()
            current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
            print(f"[MODE] Switched to: {current.value}")
            return True

        if cmd == "/mode":
            if not arg:
                current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
                print(f"[MODE] Current: {current.value}")
                print("[MODE] Available: default, acceptEdits, plan, bypassPermissions, custom, dontAsk")
                print("[MODE] Usage: /mode <name>  or  /mode next  (cycle)")
                return True
            if arg == "next":
                self.action_cycle_mode()
                current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
                print(f"[MODE] Switched to: {current.value}")
                return True
            mode_map = {
                "default": PermissionMode.DEFAULT,
                "acceptEdits": PermissionMode.ACCEPT_EDITS,
                "accept": PermissionMode.ACCEPT_EDITS,
                "plan": PermissionMode.PLAN,
                "bypassPermissions": PermissionMode.BYPASS,
                "bypass": PermissionMode.BYPASS,
                "custom": PermissionMode.CUSTOM,
                "dontAsk": PermissionMode.DONT_ASK,
            }
            new_mode = mode_map.get(arg)
            if new_mode is None:
                print(f"[MODE] Unknown mode: {arg}")
                print(f"[MODE] Available: {', '.join(mode_map.keys())}")
                return True
            if self.agent:
                self.agent.set_permission_mode(new_mode)
            if self._permission_checker:
                self._permission_checker.mode = new_mode
            print(f"[MODE] Switched to: {new_mode.value}")
            return True

        return False

    async def process_message(self, user_input: str) -> None:
        """Send a user message and stream the agent response."""
        if self.handle_command(user_input):
            return
        if self.agent is None:
            self._show_error("Agent not initialized. Call start() first.")
            return

        # Wait for MCP init to finish before sending (T9 / F10)
        if self._mcp_init_task is not None and not self._mcp_init_task.done():
            print("[MCP] Waiting for MCP servers to connect...", flush=True)
            try:
                await self._mcp_init_task
            except Exception:
                pass

        # Inject MCP tool list as a one-time system reminder (T9)
        if self._mcp_instructions and not self._mcp_reminder_injected:
            self.conversation.add_system_reminder(self._mcp_instructions)
            self._mcp_reminder_injected = True

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
            self._handle_permission_request(event)

    def _handle_permission_request(self, event: PermissionRequest) -> None:
        from mewcode.permission_dialog import InlinePermissionWidget
        tool_name = event.tool_name
        args = event.tool_args
        from mewcode.permissions.rules import extract_content
        content = extract_content(tool_name, args)
        desc = content if content else str(args)
        widget = InlinePermissionWidget(tool_name=tool_name, description=desc)
        print(f"\n{widget.render()}", flush=True)
        while True:
            try:
                choice = input("Choose [1-3]: ").strip()
                idx = int(choice) - 1
                response = widget.handle_choice(idx)
                break
            except (ValueError, EOFError, KeyboardInterrupt):
                response = PermissionResponse.DENY
                break
        event.future.set_result(response)

    @property
    def pending_ask_user_event(self) -> Any:
        """Expose AskUserTool's pending event for TUI consumption."""
        tool = self.registry.get("AskUserQuestion")
        if tool is not None and hasattr(tool, "pending_event"):
            return tool.pending_event
        return None


async def main() -> None:
    """Entry point for ``python -m mewcode``."""
    from pathlib import Path

    from mewcode.config import load_config

    config_path = Path("config.yaml")
    app_config = load_config(config_path)
    # Keep dict shape for backward-compat provider selection
    import yaml
    raw: dict[str, Any] = {"providers": []}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or raw

    app = MewCodeApp(raw, mcp_servers=app_config.mcp_servers)
    await app.start()

    print("MewCode — type a message (Ctrl+C to exit)")
    print("Commands: /plan  /do  /mode [name]  /next (cycle mode)")
    session = PromptSession(history=InMemoryHistory())
    while True:
        try:
            mode_str = ""
            if app.agent:
                mode_str = f" [{app.agent.permission_mode.value}]"
            user_input = await session.prompt_async(f"MewCode{mode_str}> ")
            if not user_input.strip():
                continue
            await app.process_message(user_input)
            print()  # newline after response
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

    await app._shutdown_mcp()


if __name__ == "__main__":
    asyncio.run(main())