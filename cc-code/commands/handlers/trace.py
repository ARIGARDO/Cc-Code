"""/trace command handler (factory, depends on TraceManager)."""

from __future__ import annotations

from typing import Any

from mewcode.commands.registry import Command, CommandContext, CommandType


def create_trace_command(trace_manager: Any) -> Command:
    async def handle_trace(ctx: CommandContext) -> None:
        parts = ctx.args.strip().split(None, 1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("", "list"):
            traces = trace_manager.list_traces()
            if not traces:
                ctx.ui.add_system_message("没有追踪记录")
                return
            lines = ["追踪记录:"]
            for t in traces[:10]:
                lines.append(f"  {t.get('id', '?')}: {t.get('summary', '')}")
            ctx.ui.add_system_message("\n".join(lines))

        elif cmd == "show":
            if not arg:
                ctx.ui.add_system_message("用法: /trace show <id>")
                return
            detail = trace_manager.get_trace(arg)
            if detail:
                ctx.ui.add_system_message(detail)
            else:
                ctx.ui.add_system_message(f"未找到追踪: {arg}")

        else:
            ctx.ui.add_system_message("用法: /trace [list | show <id>]")

    return Command(
        name="trace",
        description="追踪记录管理",
        type=CommandType.LOCAL,
        handler=handle_trace,
        usage="/trace [list | show <id>]",
    )