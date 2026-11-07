"""/do command handler."""

from __future__ import annotations

from cccode.commands.registry import Command, CommandContext, CommandType


async def handle_do(ctx: CommandContext) -> None:
    if ctx.args.strip().lower() in ("yolo", "bypass"):
        from cccode.permissions.modes import PermissionMode
        if ctx.agent:
            ctx.agent.set_permission_mode(PermissionMode.BYPASS)
        ctx.ui.add_system_message("切换到 Bypass 模式 (YOLO)")
    else:
        ctx.ui.set_plan_mode(False)
        ctx.ui.add_system_message("切换到 Default 模式")


DO_COMMAND = Command(
    name="do",
    description="切换到 Default 模式",
    type=CommandType.LOCAL_UI,
    handler=handle_do,
    usage="/do [yolo]",
)