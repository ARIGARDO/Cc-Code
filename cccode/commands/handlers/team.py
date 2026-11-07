"""/team slash command — list / info / delete teams."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cccode.commands.registry import Command

if TYPE_CHECKING:
    from cccode.commands.registry import CommandContext


async def handle_team(ctx: "CommandContext") -> None:
    """Handle /team <subcommand> ..."""

    args = ctx.args.strip()
    if not args:
        ctx.ui.add_system_message(
            "用法: /team <list|info|delete> [options]\n"
            "  list                    列出所有团队\n"
            "  info <slug>             显示团队详情(成员、任务)\n"
            "  delete <slug> [--force] 删除团队"
        )
        return

    parts = args.split()
    subcommand = parts[0].lower()
    remaining = parts[1:]

    mgr = ctx.config.get("team_manager")
    if mgr is None:
        ctx.ui.add_system_message("Team 管理器未启用")
        return

    if subcommand == "list":
        await _cmd_list(ctx, mgr)
    elif subcommand == "info":
        await _cmd_info(ctx, mgr, remaining)
    elif subcommand == "delete":
        await _cmd_delete(ctx, mgr, remaining)
    else:
        ctx.ui.add_system_message(f"未知的 team 子命令: {subcommand}")


async def _cmd_list(ctx: "CommandContext", mgr) -> None:
    try:
        teams = await mgr.list_()
    except Exception as e:
        ctx.ui.add_system_message(f"加载团队列表失败: {e}")
        return

    if not teams:
        ctx.ui.add_system_message("尚未创建任何团队。使用 TeamCreate 工具创建团队。")
        return

    lines = [f"已创建 {len(teams)} 个团队:"]
    for t in teams:
        lines.append(f"  - {t.get('name', '?')} (slug={t.get('sanitized_name', '?')})")
        desc = t.get("description", "")
        if desc:
            lines.append(f"      {desc}")
    ctx.ui.add_system_message("\n".join(lines))


async def _cmd_info(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    if not remaining:
        ctx.ui.add_system_message("用法: /team info <slug>")
        return
    slug = remaining[0]

    try:
        team = await mgr.get(slug)
    except Exception as e:
        ctx.ui.add_system_message(f"加载团队失败: {e}")
        return

    lines = [
        f"Team: {team.name}",
        f"  slug: {team.sanitized_name}",
        f"  backend: {team.backend}",
        f"  created: {team.created_at}",
    ]
    if team.description:
        lines.append(f"  description: {team.description}")

    if team.members:
        lines.append(f"  members ({len(team.members)}):")
        for m in team.members:
            status = "active" if m.is_active else "inactive"
            lines.append(
                f"    - {m.name} [{m.agent_type or '?'}] agent_id={m.agent_id or '-'} status={status}"
            )
    else:
        lines.append("  members: (none)")

    ctx.ui.add_system_message("\n".join(lines))


async def _cmd_delete(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    if not remaining:
        ctx.ui.add_system_message("用法: /team delete <slug> [--force]")
        return
    slug = remaining[0]
    force = "--force" in remaining

    try:
        await mgr.delete(slug, force=force)
        ctx.ui.add_system_message(f"团队 '{slug}' 已删除。")
    except Exception as e:
        ctx.ui.add_system_message(f"删除失败: {e}")


TEAM_COMMAND = Command(
    name="team",
    description="管理团队 (list / info / delete)",
    handler=handle_team,
)