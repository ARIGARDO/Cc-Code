"""/review command handler (PROMPT type)."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType

REVIEW_PROMPT = """请对以下代码进行审查，重点关注：
1. 逻辑错误
2. 安全问题
3. 性能问题
4. 代码风格"""


async def handle_review(ctx: CommandContext) -> None:
    text = REVIEW_PROMPT
    if ctx.args.strip():
        text += f"\n\n额外关注：{ctx.args.strip()}"
    ctx.ui.send_user_message(text)


REVIEW_COMMAND = Command(
    name="review",
    description="代码审查",
    type=CommandType.PROMPT,
    handler=handle_review,
    usage="/review [额外关注点]",
    arg_prompt="额外关注点",
)