"""/worktree command handler (factory, depends on WorktreeManager)."""

from __future__ import annotations

from typing import Any

from mewcode.commands.registry import Command, CommandContext, CommandType


def create_worktree_command(worktree_manager: Any) -> Command:
    async def handle_worktree(ctx: CommandContext) -> None:
        parts = ctx.args.strip().split(None, 1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("", "list"):
            branches = worktree_manager.list_branches()
            current = worktree_manager.current_branch()
            lines = ["分支列表:"]
            for b in branches:
                marker = " *" if b == current else ""
                lines.append(f"  {b}{marker}")
            ctx.ui.add_system_message("\n".join(lines))

        elif cmd == "switch":
            if not arg:
                ctx.ui.add_system_message("用法: /worktree switch <branch>")
                return
            worktree_manager.switch_branch(arg)
            ctx.ui.add_system_message(f"已切换到: {arg}")

        elif cmd == "create":
            if not arg:
                ctx.ui.add_system_message("用法: /worktree create <name>")
                return
            worktree_manager.create_branch(arg)
            ctx.ui.add_system_message(f"已创建分支: {arg}")

        elif cmd == "status":
            status = worktree_manager.status()
            ctx.ui.add_system_message(status)

        else:
            ctx.ui.add_system_message(
                "用法: /worktree [list | switch <branch> | create <name> | status]"
            )

    return Command(
        name="worktree",
        description="工作树管理",
        type=CommandType.LOCAL_UI,
        handler=handle_worktree,
        usage="/worktree [list | switch <branch> | create <name> | status]",
    )