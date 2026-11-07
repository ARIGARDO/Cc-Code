"""/skill command handler: list | info <name> | reload."""

from __future__ import annotations

from cccode.commands.registry import Command, CommandContext, CommandType


async def handle_skill(ctx: CommandContext) -> None:
    parts = ctx.args.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    skill_loader = ctx.config.get("skill_loader")
    skill_executor = ctx.config.get("skill_executor")

    if cmd in ("", "list"):
        if skill_loader is None:
            ctx.ui.add_system_message("Skill 加载器未初始化")
            return
        catalog = skill_loader.get_catalog()
        if not catalog:
            ctx.ui.add_system_message("没有已加载的 Skill")
            return
        lines = ["已加载的 Skill:"]
        for name, desc in catalog:
            source = skill_loader.get_source_label(name)
            lines.append(f"  {name:<20} {desc}  [{source}]")
        ctx.ui.add_system_message("\n".join(lines))

    elif cmd == "info":
        if not arg:
            ctx.ui.add_system_message("用法: /skill info <skill_name>")
            return
        if skill_loader is None:
            ctx.ui.add_system_message("Skill 加载器未初始化")
            return
        skill = skill_loader.get(arg)
        if skill is None:
            ctx.ui.add_system_message(f"未找到 Skill: {arg}")
            return
        lines = [
            f"Name: {skill.name}",
            f"Description: {skill.description}",
            f"Mode: {skill.mode}",
            f"Context: {skill.context}",
            f"Model: {skill.model or '(default)'}",
            f"AllowedTools: {', '.join(skill.allowed_tools) if skill.allowed_tools else '(all)'}",
            f"Source: {skill_loader.get_source_label(skill.name)}",
            f"Path: {skill.source_path}",
            f"Directory: {skill.is_directory}",
        ]
        ctx.ui.add_system_message("\n".join(lines))

    elif cmd == "reload":
        if skill_loader is None:
            ctx.ui.add_system_message("Skill 加载器未初始化")
            return
        try:
            skill_loader.reload()
            if skill_executor and skill_loader:
                from cccode.commands.handlers.skill_register import register_skill_commands
                command_registry = ctx.config.get("registry")
                if command_registry:
                    register_skill_commands(command_registry, skill_loader, skill_executor)
            ctx.ui.add_system_message("Skill 已重新加载")
        except Exception as e:
            ctx.ui.add_system_message(f"重新加载失败: {e}")

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