"""/permission command handler."""

from __future__ import annotations

from cccode.commands.registry import Command, CommandContext, CommandType


async def handle_permission(ctx: CommandContext) -> None:
    agent = ctx.agent

    parts = ctx.args.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("", "mode"):
        if not arg:
            from cccode.permissions.modes import PermissionMode
            current = agent.permission_mode if agent else PermissionMode.DEFAULT
            ctx.ui.add_system_message(f"当前模式: {current.value}")
            ctx.ui.add_system_message(
                "可用模式: default, acceptEdits, plan, bypassPermissions, custom, dontAsk"
            )
            return
        from cccode.permissions.modes import PermissionMode
        mode_map = {
            "default": PermissionMode.DEFAULT,
            "acceptEdits": PermissionMode.ACCEPT_EDITS,
            "accept": PermissionMode.ACCEPT_EDITS,
            "plan": PermissionMode.PLAN,
            "bypassPermissions": PermissionMode.BYPASS,
            "bypass": PermissionMode.BYPASS,
            "custom": PermissionMode.CUSTOM,
            "dontAsk": PermissionMode.DONT_ASK,
        }
        new_mode = mode_map.get(arg)
        if new_mode is None:
            ctx.ui.add_system_message(f"未知模式: {arg}")
            ctx.ui.add_system_message(f"可用: {', '.join(mode_map.keys())}")
            return
        if agent:
            agent.set_permission_mode(new_mode)
        ctx.ui.add_system_message(f"切换到: {new_mode.value}")

    elif cmd == "next":
        from cccode.permissions.modes import PermissionMode
        _MODE_CYCLE = [
            PermissionMode.DEFAULT,
            PermissionMode.ACCEPT_EDITS,
            PermissionMode.PLAN,
            PermissionMode.BYPASS,
            PermissionMode.CUSTOM,
            PermissionMode.DONT_ASK,
        ]
        if agent:
            current = agent.permission_mode
            try:
                idx = _MODE_CYCLE.index(current)
                next_idx = (idx + 1) % len(_MODE_CYCLE)
            except ValueError:
                next_idx = 0
            new_mode = _MODE_CYCLE[next_idx]
            agent.set_permission_mode(new_mode)
            ctx.ui.add_system_message(f"切换到: {new_mode.value}")

    elif cmd == "rules":
        ctx.ui.add_system_message("权限规则管理 (暂未实现)")

    elif cmd == "add":
        ctx.ui.add_system_message("添加权限规则 (暂未实现)")

    elif cmd == "reset":
        ctx.ui.add_system_message("重置权限规则 (暂未实现)")

    else:
        ctx.ui.add_system_message("用法: /permission [mode | next | rules | add | reset]")


PERMISSION_COMMAND = Command(
    name="permission",
    description="权限模式管理",
    type=CommandType.LOCAL_UI,
    handler=handle_permission,
    aliases=["mode"],
    usage="/permission [mode <name> | next]",
)