"""Worktree slash command handler — /worktree create/list/enter/exit/remove."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.commands.registry import Command
from mewcode.worktree.lifecycle import ExitAction, ExitOptions, WorktreeHasChangesError

if TYPE_CHECKING:
    from mewcode.commands.registry import CommandContext


async def handle_worktree(ctx: "CommandContext") -> None:
    """Handle /worktree <subcommand> ..."""
    args = ctx.args.strip()
    if not args:
        ctx.ui.add_system_message(
            "用法: /worktree <create|list|enter|exit|remove> [options]\n"
            "  create <slug>         创建 Worktree\n"
            "  list                  列出所有 Worktree\n"
            "  enter <slug>          进入 Worktree\n"
            "  exit [--remove] [--discard]  退出当前 Worktree\n"
            "  remove <slug> [--discard]    删除 Worktree"
        )
        return

    parts = args.split()
    subcommand = parts[0].lower()
    remaining = parts[1:]

    mgr = ctx.config.get("worktree_manager")
    if mgr is None:
        ctx.ui.add_system_message("Worktree 管理器未启用(当前目录不是 git 仓库)")
        return

    if subcommand == "create":
        await _cmd_create(ctx, mgr, remaining)
    elif subcommand == "list":
        await _cmd_list(ctx, mgr)
    elif subcommand == "enter":
        await _cmd_enter(ctx, mgr, remaining)
    elif subcommand == "exit":
        await _cmd_exit(ctx, mgr, remaining)
    elif subcommand == "remove":
        await _cmd_remove(ctx, mgr, remaining)
    else:
        ctx.ui.add_system_message(f"未知的 worktree 子命令: {subcommand}")


async def _cmd_create(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    if not remaining:
        ctx.ui.add_system_message("用法: /worktree create <slug>")
        return
    slug = remaining[0]
    try:
        wt = await mgr.create(slug, "HEAD", manual=True)
        ctx.ui.add_system_message(f"Worktree 已创建: {wt.path} (分支 {wt.branch})")
    except ValueError as e:
        ctx.ui.add_system_message(f"创建失败: {e}")
    except RuntimeError as e:
        ctx.ui.add_system_message(f"创建失败: {e}")


async def _cmd_list(ctx: "CommandContext", mgr) -> None:
    wts = mgr.list()
    if not wts:
        ctx.ui.add_system_message("没有 Worktree")
        return

    current_name = None
    session = mgr.get_current_session()
    if session:
        current_name = session.worktree_name

    lines = []
    for wt in wts:
        flags = []
        if wt.name == current_name:
            flags.append("active")
        if wt.manual:
            flags.append("manual")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"  {wt.name}  {wt.path}  {wt.branch}{flag_str}")

    ctx.ui.add_system_message("Worktree 列表:\n" + "\n".join(lines))


async def _cmd_enter(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    if not remaining:
        ctx.ui.add_system_message("用法: /worktree enter <slug>")
        return
    slug = remaining[0]
    try:
        session = await mgr.enter(slug)
        ctx.ui.add_system_message(f"已进入 {slug}: {session.worktree_path}")

        set_active_cwd = ctx.config.get("set_active_cwd")
        if set_active_cwd:
            set_active_cwd(session.worktree_path)
    except ValueError as e:
        ctx.ui.add_system_message(f"进入失败: {e}")


async def _cmd_exit(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    session = mgr.get_current_session()
    if session is None:
        ctx.ui.add_system_message("当前没有活跃的 worktree session")
        return

    remove = "--remove" in remaining
    discard = "--discard" in remaining

    action = ExitAction.REMOVE if remove else ExitAction.KEEP
    opts = ExitOptions(discard_changes=discard)

    try:
        report = await mgr.exit(session.worktree_name, action, opts)
        if report.removed:
            ctx.ui.add_system_message(f"已退出并删除 worktree '{session.worktree_name}'")
        else:
            ctx.ui.add_system_message(f"已退出 worktree '{session.worktree_name}'")

        set_active_cwd = ctx.config.get("set_active_cwd")
        if set_active_cwd:
            set_active_cwd("")
    except WorktreeHasChangesError as e:
        ctx.ui.add_system_message(f"错误: {e}")
    except ValueError as e:
        ctx.ui.add_system_message(f"退出失败: {e}")


async def _cmd_remove(ctx: "CommandContext", mgr, remaining: list[str]) -> None:
    if not remaining:
        ctx.ui.add_system_message("用法: /worktree remove <slug> [--discard]")
        return

    slug = remaining[0]
    discard = "--discard" in remaining

    try:
        await mgr.remove(slug, ExitOptions(discard_changes=discard))
        ctx.ui.add_system_message(f"已删除 worktree '{slug}'")
    except WorktreeHasChangesError as e:
        ctx.ui.add_system_message(f"错误: {e}")
    except ValueError as e:
        ctx.ui.add_system_message(f"删除失败: {e}")


WORKTREE_COMMAND = Command(
    name="worktree",
    description="Git Worktree 隔离管理",
    handler=handle_worktree,
)