"""/status command handler."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_status(ctx: CommandContext) -> None:
    agent = ctx.agent
    session = ctx.session
    memory_manager = ctx.memory_manager

    lines = ["\033[1mCcCode 状态\033[0m"]

    if agent:
        from mewcode.permissions.modes import PermissionMode
        mode = agent.permission_mode if hasattr(agent, "permission_mode") else PermissionMode.DEFAULT
        lines.append(f"  模式: {mode.value}")

    if session and session.meta:
        m = session.meta
        lines.append(
            f"  会话: {m.id} ({m.message_count}条消息)"
            f" - 最后活跃: {m.last_active.strftime('%Y-%m-%d %H:%M')}"
        )

    token_count = None
    if hasattr(ctx.ui, "get_token_count"):
        try:
            token_count = ctx.ui.get_token_count()
        except Exception:
            pass
    if token_count:
        lines.append(f"  Token: 输入{token_count[0]:,} / 输出{token_count[1]:,}")

    lines.append(f"  工具: {len(agent.registry.list_tools()) if agent else 0} 个已注册")

    memory_status = "未初始化"
    if memory_manager:
        has_user = memory_manager.user_path.is_file() if memory_manager.user_path else False
        has_project = memory_manager.project_path.is_file() if memory_manager.project_path else False
        parts = []
        if has_user:
            parts.append("用户级")
        if has_project:
            parts.append("项目级")
        memory_status = ", ".join(parts) if parts else "空"
    lines.append(f"  记忆: {memory_status}")

    lines.append(f"  工作目录: {ctx.config.get('work_dir', '未知')}")
    lines.append("  版本: v0.1.0")

    ctx.ui.add_system_message("\n".join(lines))


STATUS_COMMAND = Command(
    name="status",
    description="显示 CcCode 状态信息",
    type=CommandType.LOCAL,
    handler=handle_status,
    aliases=["s"],
    usage="/status",
)