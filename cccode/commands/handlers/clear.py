"""/clear command handler."""

from __future__ import annotations

from cccode.commands.registry import Command, CommandContext, CommandType


async def handle_clear(ctx: CommandContext) -> None:
    clear_chat = ctx.config.get("clear_chat")
    if clear_chat:
        clear_chat()
    if ctx.conversation:
        ctx.conversation.clear()
    if ctx.agent:
        ctx.agent.clear_active_skills()
    ctx.ui.add_system_message("对话已清空")


CLEAR_COMMAND = Command(
    name="clear",
    description="清空对话历史",
    type=CommandType.LOCAL_UI,
    handler=handle_clear,
    usage="/clear",
)