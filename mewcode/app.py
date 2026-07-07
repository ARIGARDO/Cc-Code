"""MewCode TUI application.

Wires together provider selection, LLM client, Agent, ToolRegistry, and the Textual UI.
Layout matches the reference design:
  - Header: ASCII cat logo + version + model + workdir
  - Status bar: MCP connection status
  - Chat output (scrollable)
  - Input bar at bottom
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

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
    PersistNotification,
    PermissionMode,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    UsageEvent,
)
from mewcode.permissions.checker import PermissionChecker
from mewcode.permissions.dangerous import DangerousCommandDetector
from mewcode.permissions.rules import RuleEngine
from mewcode.permissions.sandbox import PathSandbox
from mewcode.tui import ChatOutput, MCPStatus, MewCodeHeader, TUILayout
from mewcode.tools import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)

_MODE_CYCLE = [
    PermissionMode.DEFAULT,
    PermissionMode.ACCEPT_EDITS,
    PermissionMode.PLAN,
    PermissionMode.BYPASS,
    PermissionMode.CUSTOM,
    PermissionMode.DONT_ASK,
]


class MewCodeApp(App):
    """Textual-based TUI for MewCode.

    CSS_CLASS = "mewcode"
    TITLE = "MewCode"
    SUB_TITLE = "AI Coding Assistant"
    """

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
        height: 100%;
    }
    TUILayout {
        height: 1fr;
    }
    #user_input {
        padding: 0 1;
        border-top: solid $primary;
        height: auto;
    }
    #mode_bar {
        height: 1;
        padding: 0 1;
        color: $text-disabled;
        background: $surface;
    }
    #permission_area {
        height: auto;
        width: 100%;
        background: $surface;
        display: none;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("shift+tab", "cycle_mode", "Cycle mode"),
    ]

    def __init__(
        self,
        config: dict[str, Any],
        mcp_servers: Optional[list[MCPServerConfig]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config
        self.client: Any = None
        self.agent: Optional[Agent] = None
        self.conversation = ConversationManager()
        self.file_cache = FileCache()
        self.registry: ToolRegistry = create_default_registry(file_cache=self.file_cache)
        self._provider: Optional[ProviderConfig] = None
        self._work_dir: Path = Path.cwd()
        self._permission_checker: Optional[PermissionChecker] = None

        # MCP integration (T9 / ch07)
        self._mcp_server_configs: list[MCPServerConfig] = list(mcp_servers or [])
        self._mcp_manager: Optional[Any] = None
        self._mcp_ready: bool = False
        self._mcp_instructions: str = ""
        self._mcp_reminder_injected: bool = False

        # UI widget references (set in on_mount)
        self._header: Optional[MewCodeHeader] = None
        self._mcp_status: Optional[MCPStatus] = None
        self._chat_output: Optional[ChatOutput] = None
        self._input_widget: Optional[Input] = None
        self._mode_bar: Optional[Static] = None

    def compose(self) -> ComposeResult:
        yield TUILayout()
        yield Static(id="permission_area")
        yield Input(placeholder="Send a message...", id="user_input")
        yield Static(self._mode_label(), id="mode_bar")

    def on_mount(self) -> None:
        self._header = self.query_one(MewCodeHeader)
        self._mcp_status = self.query_one(MCPStatus)
        self._chat_output = self.query_one(ChatOutput)
        self._mode_bar = self.query_one("#mode_bar", Static)

        # Update header with current info
        if self._header:
            self._header.work_dir = str(self._work_dir)

        # Kick off async initialization
        self.run_worker(self._async_start(), exclusive=False)

    async def _async_start(self) -> None:
        """Async initialization called after mount."""
        try:
            await self._start_agent()
            # Kick off MCP connections after agent is ready
            if self._mcp_server_configs:
                self._mcp_status.set_connecting() if self._mcp_status else None
                self.run_worker(self._init_mcp(), name="mcp_init", exclusive=False)
        except Exception as e:
            self._show_error(f"Startup failed: {e}")

    def _select_provider(self) -> None:
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

    async def _start_agent(self) -> None:
        self._select_provider()
        if self.client is None:
            return

        protocol = self._provider.protocol if self._provider else "anthropic"
        model_display = f"{self._provider.model}" if self._provider else ""

        from mewcode.tools.impl.tool_search import ToolSearchTool
        from mewcode.tools.ask_user import AskUserTool

        self.registry.register(ToolSearchTool(self.registry, protocol=protocol))
        self.registry.register(AskUserTool())

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

        context_window = 200_000
        if self._provider:
            cw = self._raw_providers[0].get("context_window") if self._raw_providers else None
            if cw and isinstance(cw, int) and cw > 0:
                context_window = cw

        self.agent = Agent(
            client=self.client,
            registry=self.registry,
            protocol=protocol,
            work_dir=work_dir,
            context_window=context_window,
            permission_checker=self._permission_checker,
            instructions_content="You are MewCode, a terminal AI coding assistant.",
        )

        # Update header with model info
        if self._header and self._provider:
            self._header.version = "v0.1.0"
            self._header.model_name = model_display

    async def _init_mcp(self) -> None:
        from mewcode.mcp import MCPManager

        self._mcp_manager = MCPManager()
        self._mcp_manager.load_configs(self._mcp_server_configs)
        errors = await self._mcp_manager.register_all_tools(self.registry)

        if errors and self._mcp_status:
            for err in errors:
                self._append_chat_line(f"[MCP ERROR] {err}")

        tool_names = [n for n in self.registry.list_tools() if n.startswith("mcp_")]
        if tool_names:
            lines = ["The following MCP tools are available:"]
            for name in tool_names:
                tool = self.registry.get(name)
                desc = tool.description if tool else ""
                lines.append(f"- {name}: {desc}")
            self._mcp_instructions = "\n".join(lines)
            count = len(self._mcp_server_configs) - len(errors)
            if self._mcp_status:
                self._mcp_status.set_connected(count, len(tool_names))

        self._mcp_ready = True

    async def _shutdown_mcp(self) -> None:
        if self._mcp_manager is not None:
            try:
                await self._mcp_manager.shutdown()
            except Exception as e:
                logger.debug("MCP shutdown error: %s", e)
            self._mcp_manager = None

    # ── Slash command handling ────────────────

    def handle_command(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return False

        parts = stripped.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/help", "/h", "/?"):
            lines = [
                "\033[1m可用命令:\033[0m",
                "  /compact, /cmp  — 手动压缩上下文",
                "  /plan           — 切换到 Plan 模式",
                "  /do             — 切换到 Default 模式",
                "  /do yolo        — 切换到 Bypass 模式",
                "  /mode [name]    — 查看/切换权限模式",
                "  /next, /n       — 循环切换权限模式",
                "  /clear          — 清空对话历史",
                "  /help, /h       — 显示此帮助",
            ]
            for line in lines:
                self._append_chat_line(line)
            return True

        if cmd == "/plan":
            self._set_plan_mode(True)
            self._append_chat_line("[MODE] Switched to Plan mode")
            return True

        if cmd == "/do":
            if arg.lower() in ("yolo", "bypass"):
                if self.agent:
                    self.agent.set_permission_mode(PermissionMode.BYPASS)
                    if self._permission_checker:
                        self._permission_checker.mode = PermissionMode.BYPASS
                self._append_chat_line("[MODE] Switched to Bypass mode (YOLO)")
                self._update_mode_bar()
            else:
                self._set_plan_mode(False)
                self._append_chat_line("[MODE] Switched to Default mode")
            return True

        if cmd in ("/next", "/n"):
            self.action_cycle_mode()
            current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
            self._append_chat_line(f"[MODE] Switched to: {current.value}")
            return True

        if cmd == "/mode":
            if not arg:
                current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
                self._append_chat_line(f"[MODE] Current: {current.value}")
                self._append_chat_line("[MODE] Available: default, acceptEdits, plan, bypassPermissions, custom, dontAsk")
                return True
            if arg == "next":
                self.action_cycle_mode()
                current = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
                self._append_chat_line(f"[MODE] Switched to: {current.value}")
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
                self._append_chat_line(f"[MODE] Unknown mode: {arg}")
                self._append_chat_line(f"[MODE] Available: {', '.join(mode_map.keys())}")
                return True
            if self.agent:
                self.agent.set_permission_mode(new_mode)
            if self._permission_checker:
                self._permission_checker.mode = new_mode
            self._append_chat_line(f"[MODE] Switched to: {new_mode.value}")
            self._update_mode_bar()
            return True

        if cmd in ("/compact", "/cmp"):
            self.run_worker(self._do_compact(), exclusive=False)
            return True

        if cmd == "/clear":
            self.conversation.clear()
            if self._chat_output:
                self._chat_output.clear_output()
            self._append_chat_line("\033[90m[CLEAR] 对话已清空\033[0m")
            return True

        return False

    def _set_plan_mode(self, enabled: bool) -> None:
        if self.agent is None:
            return
        if enabled:
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            self.agent.set_permission_mode(PermissionMode.DEFAULT)
        self._update_mode_bar()

    async def _do_compact(self) -> None:
        if self.agent is None:
            self._append_chat_line("\033[31m[COMPACT] Agent not initialized\033[0m")
            return
        self._append_chat_line("\033[34m[COMPACT] 正在压缩上下文...\033[0m")
        result = await self.agent.manual_compact(self.conversation)
        if result:
            pct = int(
                self.conversation.last_input_tokens
                / self.agent.context_window
                * 100
            )
            self._append_chat_line(
                f"\033[34m[COMPACT] 压缩完成 (上下文占用: {self.conversation.last_input_tokens:,}/{self.agent.context_window:,} tokens, {pct}%)\033[0m"
            )
        else:
            self._append_chat_line("\033[90m[COMPACT] 无需压缩或压缩被跳过\033[0m")

    def action_cycle_mode(self) -> None:
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
        self._update_mode_bar()

    # ── Message processing ────────────────────

    async def process_message(self, user_input: str) -> None:
        if self.handle_command(user_input):
            return
        if self.agent is None:
            self._show_error("Agent not initialized. Call start() first.")
            return

        if not self._mcp_ready and self._mcp_server_configs:
            self._append_chat_line("[MCP] Waiting for MCP servers to connect...")
            for _ in range(50):
                if self._mcp_ready:
                    break
                await asyncio.sleep(0.1)

        if self._mcp_instructions and not self._mcp_reminder_injected:
            self.conversation.add_system_reminder(self._mcp_instructions)
            self._mcp_reminder_injected = True

        self.conversation.add_user_message(user_input)
        self._append_chat_line(f"\x1b[33m> {user_input}\x1b[0m")

        try:
            async for event in self.agent.run(self.conversation):
                if isinstance(event, PermissionRequest):
                    result = await self._ask_permission(event)
                    event.future.set_result(result)
                else:
                    self._render_event(event)
        except LLMError as e:
            self._show_error(str(e))
        except Exception as e:
            self._show_error(f"Unexpected error: {e}")
            logger.exception("process_message failed")

    def _render_event(self, event: Any) -> None:
        if isinstance(event, StreamText):
            self._append_text(event.text)

        elif isinstance(event, ThinkingText):
            pass

        elif isinstance(event, ToolUseEvent):
            self._append_chat_line(f"\033[36m[TOOL] {event.tool_name} ...\033[0m")

        elif isinstance(event, ToolResultEvent):
            pass

        elif isinstance(event, LoopComplete):
            self._append_chat_line("")
            if self._chat_output:
                self._chat_output._auto_scroll = True
                self._chat_output.call_after_refresh(
                    self._chat_output._do_scroll_end
                )

        elif isinstance(event, UsageEvent):
            total = event.total_input + event.total_output
            pct = ""
            if self.agent and self.agent.context_window > 0:
                ratio = event.total_input / self.agent.context_window * 100
                pct = f" | 上下文: {ratio:.0f}%"
                if self._header:
                    threshold = 80
                    if ratio >= 90:
                        tag = "⚠️ 上下文即将满"
                    elif ratio >= threshold:
                        tag = "上下文较满"
                    else:
                        tag = ""
                    self._header.context_info = (
                        f"Tokens: {event.total_input:,}/{self.agent.context_window:,} ({ratio:.0f}%) {tag}"
                    )
            self._append_chat_line(
                f"\033[90m[USAGE] 本轮 In: {event.input_tokens:,} Out: {event.output_tokens:,}"
                f" | 累计: {total:,} tokens{pct}\033[0m"
            )

        elif isinstance(event, ErrorEvent):
            self._append_chat_line(f"\033[31m[ERROR] {event.message}\033[0m")

        elif isinstance(event, RetryEvent):
            self._append_chat_line(f"\033[33m[RETRY] {event.reason}\033[0m")

        elif isinstance(event, CompactNotification):
            self._append_chat_line(f"\033[34m[COMPACT] {event.message}\033[0m")

        elif isinstance(event, PersistNotification):
            orig_kb = event.original_chars / 1024
            prev_kb = event.preview_chars / 1024
            self._append_chat_line(
                f"\033[33m[PERSIST] 工具结果 {event.tool_use_id[:16]}… "
                f"过大已存盘 ({orig_kb:.1f}KB → 预览 {prev_kb:.1f}KB)\033[0m"
            )

        elif isinstance(event, HookEvent):
            pass

    async def _ask_permission(self, event: PermissionRequest) -> PermissionResponse:
        from mewcode.permission_dialog import PermissionSelector
        from mewcode.permissions.rules import extract_content
        tool_name = event.tool_name
        args = event.tool_args
        content = extract_content(tool_name, args)
        desc = content if content else str(args)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()

        def _on_confirm(result: PermissionResponse) -> None:
            if not future.done():
                future.set_result(result)
            perm_area = self.query_one("#permission_area", Static)
            if perm_area:
                perm_area.styles.display = "none"
                perm_area.remove_children()

        selector = PermissionSelector(
            tool_name=tool_name,
            description=desc,
            on_confirm=_on_confirm,
            id="perm_selector",
        )

        perm_area = self.query_one("#permission_area", Static)
        await perm_area.mount(selector)
        perm_area.styles.display = "block"
        self.call_after_refresh(selector.focus)

        result = await future

        input_widget = self.query_one("#user_input", Input)
        input_widget.focus()

        return result

    # ── UI helpers ────────────────────────────

    def _mode_label(self) -> str:
        mode = self.agent.permission_mode if self.agent else PermissionMode.DEFAULT
        return f"  mode: {mode.value}"

    def _update_mode_bar(self) -> None:
        if self._mode_bar:
            self._mode_bar.update(self._mode_label())

    def _append_text(self, text: str) -> None:
        if self._chat_output:
            self._chat_output.append_text(text)

    def _append_chat_line(self, text: str = "", end: str = "\n") -> None:
        if self._chat_output:
            self._chat_output.append_text(text + end)

    def _show_error(self, message: str) -> None:
        self._append_chat_line(f"\033[31m[ERROR] {message}\033[0m")
        logger.error(message)

    @property
    def pending_ask_user_event(self) -> Any:
        tool = self.registry.get("AskUserQuestion")
        if tool is not None and hasattr(tool, "pending_event"):
            return tool.pending_event
        return None

    # ── Textual events ─────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return
        event.input.value = ""
        self.run_worker(self.process_message(user_input), exclusive=False)

    async def action_quit(self) -> None:
        await self._shutdown_mcp()
        self.exit()


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

async def main() -> None:
    from pathlib import Path
    from mewcode.config import load_config

    config_path = Path("config.yaml")
    app_config = load_config(config_path)

    import yaml
    raw: dict[str, Any] = {"providers": []}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or raw

    app = MewCodeApp(raw, mcp_servers=app_config.mcp_servers)
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(main())