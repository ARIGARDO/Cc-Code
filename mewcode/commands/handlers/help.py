"""/help command handler."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_help(ctx: CommandContext) -> None:
    registry = ctx.config.get("registry")
    if registry is None:
        ctx.ui.add_system_message("命令注册表未初始化")
        return

    if ctx.args.strip():
        cmd = registry.find(ctx.args.strip())
        if cmd:
            lines = [f"\033[1m/{cmd.name}\033[0m — {cmd.description}"]
            if cmd.usage:
                lines.append(f"  用法: {cmd.usage}")
            if cmd.aliases:
                lines.append(f"  别名: {', '.join('/' + a for a in cmd.aliases)}")
            ctx.ui.add_system_message("\n".join(lines))
        else:
            ctx.ui.add_system_message(f"未知命令: {ctx.args.strip()}")
        return

    commands = registry.list_commands(include_hidden=False)
    lines = ["\033[1m可用命令:\033[0m"]
    for cmd in commands:
        alias_str = f" ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
        lines.append(f"  \033[1m/{cmd.name}\033[0m{alias_str} — {cmd.description}")
    ctx.ui.add_system_message("\n".join(lines))


HELP_COMMAND = Command(
    name="help",
    description="显示可用命令",
    type=CommandType.LOCAL,
    handler=handle_help,
    aliases=["h", "?"],
    usage="/help [命令名]",
)