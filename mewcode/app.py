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
from mewcode.memory import (
    MemoryManager,
    Session,
    SessionManager,
    load_instructions,
)
from mewcode.commands.registry import CommandRegistry, CommandContext
from mewcode.commands.parser import parse_command, complete
from mewcode.commands.handlers import register_all_commands
from mewcode.commands.completion import CompletionPopup

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
        ("escape", "abort", "Abort"),
        ("shift+tab", "cycle_mode", "Cycle mode"),
    ]

    def __init__(
        self,
        config: dict[str, Any],
        mcp_servers: Optional[list[MCPServerConfig]] = None,
        hook_engine: Any = None,
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
        self.hook_engine = hook_engine

        # MCP integration (T9 / ch07)
        self._mcp_server_configs: list[MCPServerConfig] = list(mcp_servers or [])
        self._mcp_manager: Optional[Any] = None
        self._mcp_ready: bool = False
        self._mcp_instructions: str = ""
        self._mcp_reminder_injected: bool = False

        # Memory system (ch09)
        self.session_manager: Optional[SessionManager] = None
        self.session: Optional[Session] = None
        self.memory_manager: Optional[MemoryManager] = None
        self._instructions_content: str = ""

        # Streaming state
        self._streaming_worker: Optional[Any] = None
        self._history_len_before: int = 0

        # Command system (ch10)
        self.command_registry = CommandRegistry()
        register_all_commands(self.command_registry)

        # UI widget references (set in on_mount)
        self._header: Optional[MewCodeHeader] = None
        self._mcp_status: Optional[MCPStatus] = None
        self._chat_output: Optional[ChatOutput] = None
        self._input_widget: Optional[Input] = None
        self._mode_bar: Optional[Static] = None

    def compose(self) -> ComposeResult:
        yield TUILayout()
        yield CompletionPopup()
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
            # Trigger startup hook
            if self.hook_engine:
                from mewcode.hooks import HookContext
                ctx = HookContext(event_name="startup")
                asyncio.ensure_future(self.hook_engine.run_hooks("startup", ctx))
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
            raw_providers = self._config.get("providers", [])
            cw = raw_providers[0].get("context_window") if raw_providers else None
            if cw and isinstance(cw, int) and cw > 0:
                context_window = cw

        # Initialize memory system (ch09)
        self._instructions_content = load_instructions(work_dir)
        self.memory_manager = MemoryManager(work_dir)
        self.session_manager = SessionManager(work_dir)
        self.session_manager.cleanup()
        self.session = self.session_manager.create()

        # Register LoadSkill tool before Agent construction (ch11 T8)
        from mewcode.tools.load_skill import LoadSkill
        self._load_skill_tool = LoadSkill()
        self.registry.register(self._load_skill_tool)

        self.agent = Agent(
            client=self.client,
            registry=self.registry,
            protocol=protocol,
            work_dir=work_dir,
            context_window=context_window,
            permission_checker=self._permission_checker,
            instructions_content=self._instructions_content,
            memory_manager=self.memory_manager,
            hook_engine=self.hook_engine,
        )

        # Skill system (ch11 T10)
        from mewcode.skills.loader import SkillLoader
        from mewcode.skills.executor import SkillExecutor
        self.skill_loader = SkillLoader(work_dir)
        self.skill_loader.load_all()
        self._load_skill_tool.set_loader(self.skill_loader)
        self._load_skill_tool.set_agent(self.agent)
        self.skill_executor = SkillExecutor(
            agent=self.agent,
            client=self.client,
            protocol=protocol,
        )

        catalog = self.skill_loader.get_catalog()
        if catalog:
            catalog_lines = ["You can use the following Skills:\n"]
            for sname, sdesc in catalog:
                catalog_lines.append(f"- {sname}: {sdesc}")
            catalog_lines.append("\nIf the user's request matches a Skill, call LoadSkill to activate it.")
            self.agent.set_skill_catalog("\n".join(catalog_lines))

        from mewcode.commands.handlers.skill_register import register_skill_commands
        register_skill_commands(self.command_registry, self.skill_loader, self.skill_executor)

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

    # ── Slash command handling (ch10) ─────────

    def _build_command_context(self, args: str = "") -> CommandContext:
        return CommandContext(
            args=args,
            agent=self.agent,
            conversation=self.conversation,
            session=self.session,
            session_manager=self.session_manager,
            memory_manager=self.memory_manager,
            ui=self._ui_controller(),
            config={
                "registry": self.command_registry,
                "set_session": self._set_session,
                "set_conversation": self._set_conversation,
                "clear_chat": self._clear_chat,
                "render_restored": self._render_restored,
                "work_dir": str(self._work_dir),
                "skill_loader": getattr(self, "skill_loader", None),
                "skill_executor": getattr(self, "skill_executor", None),
            },
        )

    def _ui_controller(self) -> Any:
        app = self

        class _UI:
            def add_system_message(self, msg: str) -> None:
                app._append_chat_line(f"\033[36m│\033[0m {msg}")

            def send_user_message(self, text: str) -> None:
                app.run_worker(app.process_message(text), exclusive=False)

            def set_plan_mode(self, enabled: bool) -> None:
                app._set_plan_mode(enabled)

            def get_token_count(self) -> tuple[int, int]:
                if app.agent:
                    return (app.agent.total_input_tokens, app.agent.total_output_tokens)
                return (0, 0)

            def refresh_status(self) -> None:
                pass

        return _UI()

    def _set_session(self, session: Any) -> None:
        self.session = session

    def _set_conversation(self, conv: ConversationManager) -> None:
        self.conversation = conv

    def _clear_chat(self) -> None:
        if self._chat_output:
            self._chat_output.clear_output()

    def _render_restored(self) -> None:
        if self._chat_output:
            self._chat_output.clear_output()

    async def _dispatch_command(self, text: str) -> bool:
        name, args, is_command = parse_command(text)
        if not is_command:
            return False
        if not name:
            return True

        cmd = self.command_registry.find(name)
        if cmd is None:
            self._append_chat_line(f"\033[31m未知命令: /{name}\033[0m")
            return True

        ctx = self._build_command_context(args)
        try:
            result = cmd.handler(ctx)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            self._append_chat_line(f"\033[31m命令执行失败: /{name}: {e}\033[0m")
            logger.exception("Command /%s failed", name)
        return True

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
        dispatched = await self._dispatch_command(user_input)
        if dispatched:
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

        if self.session:
            from mewcode.conversation import Message
            self.session.append(Message(role="user", content=user_input))

        self._history_len_before = len(self.conversation.history)

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
        finally:
            self._streaming_worker = None

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
            if self.session:
                start = getattr(self, "_history_len_before", 0)
                for msg in self.conversation.history[start:]:
                    if msg.role == "assistant":
                        self.session.append(msg)
                    elif msg.role == "user" and msg.tool_results:
                        self.session.append(msg)
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
        popup = self.query_one(CompletionPopup)
        if popup.is_visible:
            popup.hide()
        user_input = event.value
        if not user_input or not user_input.strip():
            return
        event.input.value = ""
        self._streaming_worker = self.run_worker(
            self.process_message(user_input), exclusive=False
        )

    def on_chat_input_tab_complete(self, event: Input.TabComplete) -> None:
        text = event.input.value.strip()
        if not text.startswith("/"):
            return
        matches = complete(self.command_registry, text)
        if len(matches) == 1:
            event.input.value = matches[0]
        elif len(matches) > 1:
            popup = self.query_one(CompletionPopup)
            popup.show(matches)

    def on_completion_popup_selected(self, event: CompletionPopup.Selected) -> None:
        input_widget = self.query_one("#user_input", Input)
        input_widget.value = event.value
        input_widget.focus()

    def action_abort(self) -> None:
        if self._streaming_worker is not None:
            try:
                self._streaming_worker.cancel()
            except Exception:
                pass
            self._streaming_worker = None
            self._append_chat_line("\033[33m[ABORT] 已中断当前回复\033[0m")

    async def action_quit(self) -> None:
        # Trigger shutdown hook
        if self.hook_engine:
            from mewcode.hooks import HookContext
            ctx = HookContext(event_name="shutdown")
            await self.hook_engine.run_hooks("shutdown", ctx)
        if self.session:
            self.session.close()
        await self._shutdown_mcp()
        self.exit()


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

async def main() -> None:
    import sys
    from pathlib import Path
    from mewcode.config import load_config

    config_path = Path("config.yaml")
    app_config = load_config(config_path)

    # Load and validate hooks (ch12 T11)
    hook_engine = None
    try:
        from mewcode.hooks import HookEngine, HookConfigError, load_hooks
        hooks = load_hooks(app_config.raw_hooks)
        hook_engine = HookEngine(hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    import yaml
    raw: dict[str, Any] = {"providers": []}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or raw

    app = MewCodeApp(raw, mcp_servers=app_config.mcp_servers, hook_engine=hook_engine)
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(main())