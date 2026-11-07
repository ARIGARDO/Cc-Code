"""/compact command handler."""

from __future__ import annotations

from cccode.commands.registry import Command, CommandContext, CommandType


async def handle_compact(ctx: CommandContext) -> None:
    agent = ctx.agent
    if agent is None:
        ctx.ui.add_system_message("Agent 未初始化")
        return
    conversation = ctx.conversation
    if conversation is None:
        ctx.ui.add_system_message("对话管理器未初始化")
        return
    ctx.ui.add_system_message("正在压缩上下文...")
    result = await agent.manual_compact(conversation)
    if result:
        pct = int(conversation.last_input_tokens / agent.context_window * 100)
        ctx.ui.add_system_message(
            f"压缩完成 (上下文占用: {conversation.last_input_tokens:,}/{agent.context_window:,} tokens, {pct}%)"
        )
    else:
        ctx.ui.add_system_message("无需压缩或压缩被跳过")


COMPACT_COMMAND = Command(
    name="compact",
    description="手动压缩上下文",
    type=CommandType.LOCAL,
    handler=handle_compact,
    aliases=["c"],
    usage="/compact",
)