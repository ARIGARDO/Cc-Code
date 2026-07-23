"""/plan command handler."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_plan(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(True)
    if ctx.args.strip():
        ctx.ui.send_user_message(ctx.args.strip())


PLAN_COMMAND = Command(
    name="plan",
    description="切换到 Plan 模式",
    type=CommandType.LOCAL_UI,
    handler=handle_plan,
    aliases=["p"],
    usage="/plan [描述]",
    arg_prompt="描述",
)