"""/memory command handler."""

from __future__ import annotations

from typing import Any


def handle_memory(ctx: Any, subcmd: str = "") -> None:
    memory_manager = getattr(ctx, "memory_manager", None)
    if memory_manager is None:
        ctx.ui.add_system_message("记忆管理器未初始化")
        return

    cmd = subcmd.strip().lower() if subcmd else ""

    if cmd in ("", "list"):
        text = memory_manager.get_display_text()
        ctx.ui.add_system_message(text)

    elif cmd == "clear":
        memory_manager.clear()
        ctx.ui.add_system_message("所有自动记忆已清空。")

    elif cmd == "edit":
        ctx.ui.add_system_message(f"用户级: {memory_manager.user_path}")
        ctx.ui.add_system_message(f"项目级: {memory_manager.project_path}")

    else:
        ctx.ui.add_system_message("用法: /memory [list | clear | edit]")


MEMORY_COMMAND = {
    "name": "memory",
    "description": "记忆管理",
    "usage": "/memory [list | clear | edit]",
    "handler": handle_memory,
}