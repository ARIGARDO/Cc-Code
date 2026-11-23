"""Local-only browser transport for the existing Agent runtime."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from cccode.agent import PermissionRequest, PermissionResponse
from cccode.app import CcCodeApp
from cccode.config import load_config
from cccode.conversation import Message
from cccode.hooks import HookEngine, load_hooks
from cccode.tools.ctx import with_cwd

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class BrowserRuntime(CcCodeApp):
    """Adapt the existing initialization and command system to a WebSocket."""

    def __init__(self, ws: web.WebSocketResponse, config: dict, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.ws = ws
        self.running: asyncio.Task | None = None
        self.permission: asyncio.Future | None = None
        self.question_future: asyncio.Future | None = None
        self.question_token: int | None = None
        self.command_prompt: str | None = None

    async def send(self, kind: str, **data: Any) -> None:
        if not self.ws.closed:
            await self.ws.send_json({"type": kind, **data})

    def emit(self, kind: str, **data: Any) -> None:
        asyncio.create_task(self.send(kind, **data))

    def _append_chat_line(self, text: str = "", end: str = "\n") -> None:
        self.emit("notice", text=ANSI.sub("", text))

    def _append_text(self, text: str) -> None:
        self.emit("text", text=ANSI.sub("", text))

    def _show_error(self, message: str) -> None:
        self.emit("error", message=message)

    def _update_mode_bar(self) -> None:
        self.emit("status", mode=self.agent.permission_mode.value if self.agent else "default")

    def _clear_chat(self) -> None:
        self.emit("clear")

    def _render_restored(self) -> None:
        self.emit("restore", messages=self.restore_messages(self.conversation.history))

    @staticmethod
    def restore_messages(history: list[Message]) -> list[dict[str, Any]]:
        return [{"role": m.role, "text": m.content,
                 "thinking": [b.thinking for b in m.thinking_blocks],
                 "tool_uses": [asdict(b) for b in m.tool_uses],
                 "tool_results": [asdict(b) for b in m.tool_results]}
                for m in history if m.role in ("user", "assistant") and
                (m.content or m.thinking_blocks or m.tool_uses or m.tool_results)]

    async def send_sessions(self) -> None:
        if not self.session_manager:
            return
        await self.send("sessions", current=self.session.session_id if self.session else "", sessions=[
            {"id": meta.id, "title": meta.title or "新对话", "last_active": meta.last_active.isoformat()}
            for meta in self.session_manager.list() if meta.message_count or (self.session and meta.id == self.session.session_id)
        ])

    async def resume_session(self, session_id: str) -> None:
        if not self.session_manager or not any(meta.id == session_id for meta in self.session_manager.list()):
            await self.send("error", message="找不到该会话。")
            return
        result = self.session_manager.resume(session_id)
        if result is None:
            await self.send("error", message="无法恢复该会话。")
            return
        if self.session:
            self.session.close()
        self.session = result.session
        self.conversation.replace_history(result.messages)
        self._mcp_reminder_injected = False
        await self.send("restore", messages=self.restore_messages(result.messages))
        await self.send_sessions()

    def _ui_controller(self) -> Any:
        ui = super()._ui_controller()
        ui.send_user_message = lambda text: setattr(self, "command_prompt", text)
        return ui

    def run_worker(self, work: Any, **kwargs: Any) -> asyncio.Task:
        return asyncio.create_task(work)

    async def start(self, *, initialize_mcp: bool = True) -> None:
        await self._start_agent()
        if not self.agent:
            raise RuntimeError("未配置模型，请在 config.yaml 的 providers 中添加模型。")
        if self.hook_engine:
            from cccode.hooks import HookContext
            await self.hook_engine.run_hooks("startup", HookContext(event_name="startup"))
        if initialize_mcp and self._mcp_server_configs:
            await self._init_mcp()
        if not initialize_mcp:
            return
        await self.announce_ready()

    async def announce_ready(self) -> None:
        await self.send("ready", model=self._provider.model if self._provider else "", cwd=str(self._work_dir), mode=self.agent.permission_mode.value)
        await self.send_sessions()

    async def watch_questions(self) -> None:
        tool = self.registry.get("AskUserQuestion")
        while True:
            event = getattr(tool, "pending_event", None)
            if event and id(event) != self.question_token:
                self.question_token = id(event)
                self.question_future = event.future
                await self.send("question", questions=[q.model_dump() for q in event.questions])
            await asyncio.sleep(0.1)

    async def process(self, text: str) -> None:
        watcher = asyncio.create_task(self.watch_questions())
        before: int | None = None
        try:
            await self.send("busy", busy=True)
            if text == "/new":
                if self.session:
                    self.session.close()
                self.session = self.session_manager.create() if self.session_manager else None
                self.conversation.clear()
                self.agent.clear_active_skills()
                self._mcp_reminder_injected = False
                await self.send("clear")
                await self.send_sessions()
                return
            if text.startswith("/"):
                self.command_prompt = None
                if await self._dispatch_command(text):
                    if not self.command_prompt:
                        return
                    text = self.command_prompt
            if self._mcp_instructions and not self._mcp_reminder_injected:
                self.conversation.add_system_reminder(self._mcp_instructions)
                self._mcp_reminder_injected = True
            self.conversation.add_user_message(text)
            if self.session:
                self.session.append(Message(role="user", content=text))
                await self.send_sessions()
            before = len(self.conversation.history)
            with with_cwd(self._effective_cwd()):
                async for event in self.agent.run(self.conversation):
                    if isinstance(event, PermissionRequest):
                        self.permission = event.future
                        await self.send("permission", tool=event.tool_name, args=event.tool_args)
                    elif is_dataclass(event):
                        await self.send("agent_event", event=type(event).__name__, data=asdict(event))
        except asyncio.CancelledError:
            await self.send("notice", text="已停止运行。")
            raise
        except Exception as exc:
            logger.exception("Agent execution failed")
            await self.send("error", message=str(exc))
        finally:
            watcher.cancel()
            if before is not None and self.session:
                try:
                    for msg in self.conversation.history[before:]:
                        if msg.role == "assistant" or (msg.role == "user" and msg.tool_results):
                            self.session.append(msg)
                except Exception:
                    logger.exception("Failed to persist partial conversation")
            if self.permission and not self.permission.done():
                self.permission.cancel()
            self.permission = None
            self.question_future = None
            self.question_token = None
            self.running = None
            await self.send("busy", busy=False)

    async def close(self) -> None:
        if self.running:
            self.running.cancel()
            await asyncio.gather(self.running, return_exceptions=True)
        await self._shutdown_mcp()
        if self.session:
            self.session.close()


def same_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin", "")
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.netloc == request.host and parsed.hostname in ("127.0.0.1", "localhost", "::1")


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


async def websocket(request: web.Request) -> web.WebSocketResponse:
    if not same_origin(request):
        raise web.HTTPForbidden(text="Invalid origin")
    ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=30)
    await ws.prepare(request)
    runtime = None
    try:
        try:
            config = load_config(Path("config.yaml"))
        except Exception as exc:
            logger.warning("Invalid configuration: %s", type(exc).__name__)
            await ws.send_json({"type": "error", "message": "配置加载失败，请检查 config.yaml 的格式和配置项。"})
            return ws
        runtime = BrowserRuntime(ws, {"providers": config.providers}, mcp_servers=config.mcp_servers, hook_engine=HookEngine(load_hooks(config.raw_hooks)))
        await runtime.start()
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(message.data)
                kind = data.get("type")
                if kind == "message" and isinstance(data.get("text"), str):
                    text = data["text"].strip()
                    if text and not runtime.running:
                        runtime.running = asyncio.create_task(runtime.process(text))
                elif kind == "resume" and isinstance(data.get("session_id"), str) and not runtime.running:
                    await runtime.resume_session(data["session_id"])
                elif kind == "complete" and isinstance(data.get("text"), str):
                    from cccode.commands.parser import complete
                    query = data["text"].strip()
                    entries = [{"value": value, "description": runtime.command_registry.find(value[1:]).description, "group": "command"} for value in complete(runtime.command_registry, query)]
                    if query.startswith("/") and " " not in query and getattr(runtime, "skill_loader", None):
                        prefix = query[1:].lower()
                        skill_prefix = "" if "skill".startswith(prefix) or prefix == "skills" else prefix
                        registered = getattr(runtime.command_registry, "_registered_skill_names", set())
                        entries.extend({"value": "/" + name, "description": desc, "group": "skill", "source": runtime.skill_loader.get_source_label(name)} for name, desc in runtime.skill_loader.get_catalog() if name in registered and name.lower().startswith(skill_prefix))
                    await runtime.send("completions", query=data["text"], entries=entries[:30])
                elif kind == "workspace" and isinstance(data.get("path"), str) and not runtime.running:
                    path = Path(data["path"]).expanduser().resolve()
                    if not path.is_dir():
                        await runtime.send("error", message="项目文件夹不存在或不是文件夹。")
                        continue
                    candidate = BrowserRuntime(ws, {"providers": config.providers}, mcp_servers=config.mcp_servers, hook_engine=HookEngine(load_hooks(config.raw_hooks)))
                    candidate._work_dir = path
                    try:
                        await candidate.start(initialize_mcp=False)
                    except Exception:
                        logger.exception("Workspace initialization failed")
                        await candidate.close()
                        await runtime.send("error", message="无法打开该项目文件夹，请检查访问权限。")
                        continue
                    await runtime.close()
                    runtime = candidate
                    if runtime._mcp_server_configs:
                        await runtime._init_mcp()
                    await runtime.announce_ready()
                    await runtime.send("clear")
                elif kind == "stop" and runtime.running:
                    runtime.running.cancel()
                elif kind == "permission" and runtime.permission and not runtime.permission.done():
                    value = data.get("value")
                    if value in {x.value for x in PermissionResponse}:
                        runtime.permission.set_result(PermissionResponse(value))
                        runtime.permission = None
                elif kind == "answer" and runtime.question_future and not runtime.question_future.done():
                    answers = data.get("answers")
                    if isinstance(answers, dict):
                        runtime.question_future.set_result(answers)
                elif kind == "mode" and runtime.agent and not runtime.running:
                    from cccode.permissions.modes import PermissionMode
                    try:
                        runtime.agent.set_permission_mode(PermissionMode(data.get("value")))
                        runtime._update_mode_bar()
                    except ValueError:
                        pass
            except (ValueError, TypeError, AttributeError):
                await runtime.send("error", message="无效的请求。")
    except Exception as exc:
        logger.exception("Browser startup failed")
        if not ws.closed:
            await ws.send_json({"type": "error", "message": f"启动失败：{exc}"})
    finally:
        if runtime is not None:
            await runtime.close()
        await ws.close()
    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static/", STATIC)
    return app


def main() -> None:
    web.run_app(create_app(), host="127.0.0.1", port=8765, print=lambda _: print("CcCode: http://127.0.0.1:8765"))
