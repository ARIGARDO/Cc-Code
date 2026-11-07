"""/tasks command handler (factory, depends on TaskManager)."""

from __future__ import annotations

from typing import Any

from cccode.commands.registry import Command, CommandContext, CommandType


def create_tasks_handler(task_manager: Any) -> Any:
    async def handle_tasks(ctx: CommandContext) -> None:
        parts = ctx.args.strip().split(None, 1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("", "list"):
            tasks = task_manager.list_tasks()
            if not tasks:
                ctx.ui.add_system_message("没有任务")
                return
            lines = ["任务列表:"]
            for t in tasks:
                status = t.get("status", "unknown")
                name = t.get("name", "")
                lines.append(f"  [{status}] {name}")
            ctx.ui.add_system_message("\n".join(lines))

        elif cmd == "add":
            if not arg:
                ctx.ui.add_system_message("用法: /tasks add <描述>")
                return
            task_manager.add_task(arg)
            ctx.ui.add_system_message(f"已添加任务: {arg}")

        elif cmd == "done":
            if not arg:
                ctx.ui.add_system_message("用法: /tasks done <序号>")
                return
            task_manager.complete_task(arg)
            ctx.ui.add_system_message(f"已完成任务: {arg}")

        else:
            ctx.ui.add_system_message("用法: /tasks [list | add <描述> | done <序号>]")

    return handle_tasks


def create_tasks_command(task_manager: Any) -> Command:
    handler = create_tasks_handler(task_manager)
    return Command(
        name="tasks",
        description="任务管理",
        type=CommandType.LOCAL,
        handler=handler,
        usage="/tasks [list | add <描述> | done <序号>]",
    )