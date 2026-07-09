"""/skill command handler."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_skill(ctx: CommandContext) -> None:
    parts = ctx.args.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    skill_loader = ctx.config.get("skill_loader")

    if cmd in ("", "list"):
        if skill_loader is None:
            ctx.ui.add_system_message("Skill 加载器未初始化")
            return
        skills = getattr(skill_loader, "list_skills", lambda: [])()
        if not skills:
            ctx.ui.add_system_message("没有已加载的 Skill")
            return
        lines = ["已加载的 Skill:"]
        for name, desc in skills:
            lines.append(f"  {name}: {desc}")
        ctx.ui.add_system_message("\n".join(lines))

    elif cmd == "info":
        if not arg:
            ctx.ui.add_system_message("用法: /skill info <skill_name>")
            return
        if skill_loader is None:
            ctx.ui.add_system_message("Skill 加载器未初始化")
            return
        info_func = getattr(skill_loader, "get_skill_info", None)
        if info_func:
            info = info_func(arg)
            if info:
                ctx.ui.add_system_message(info)
            else:
                ctx.ui.add_system_message(f"未找到 Skill: {arg}")

    elif cmd == "reload":
        reload_func = ctx.config.get("skill_reload")
        if reload_func:
            try:
                await reload_func()
                ctx.ui.add_system_message("Skill 已重新加载")
            except Exception as e:
                ctx.ui.add_system_message(f"重新加载失败: {e}")
        else:
            ctx.ui.add_system_message("Skill 重新加载功能不可用")

    else:
        ctx.ui.add_system_message("用法: /skill [list | info <name> | reload]")


SKILL_COMMAND = Command(
    name="skill",
    description="Skill 管理",
    type=CommandType.LOCAL,
    handler=handle_skill,
    aliases=["skills"],
    usage="/skill [list | info <name> | reload]",
)