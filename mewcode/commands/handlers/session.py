"""/session command handler."""

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_session(ctx: CommandContext) -> None:
    session_manager = ctx.session_manager
    session = ctx.session

    if session_manager is None:
        ctx.ui.add_system_message("会话管理器未初始化")
        return

    parts = ctx.args.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "" and not ctx.args.strip():
        if session and session.meta:
            m = session.meta
            ctx.ui.add_system_message(
                f"当前会话: {m.id}\n"
                f"标题: {m.title or '(无)'}\n"
                f"消息数: {m.message_count}\n"
                f"Token: {m.total_tokens:,}\n"
                f"最后活跃: {m.last_active.strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            ctx.ui.add_system_message("无活跃会话")
        return

    if cmd == "list":
        metas = session_manager.list()[:10]
        if not metas:
            ctx.ui.add_system_message("没有历史会话")
            return
        lines = ["历史会话:"]
        for i, m in enumerate(metas, 1):
            lines.append(
                f"  {i}. [{m.id}] {m.title or '(无标题)'} "
                f"- {m.message_count}条消息 "
                f"- {m.last_active.strftime('%m-%d %H:%M')}"
            )
        ctx.ui.add_system_message("\n".join(lines))

    elif cmd == "resume":
        session_id = arg
        if not session_id:
            metas = session_manager.list()[:15]
            if not metas:
                ctx.ui.add_system_message("没有可恢复的会话")
                return
            candidates = []
            lines = ["可恢复的会话:"]
            for i, m in enumerate(metas, 1):
                candidates.append(m.id)
                lines.append(
                    f"  {i}. [{m.id}] {m.title or '(无标题)'} "
                    f"- {m.last_active.strftime('%m-%d %H:%M')}"
                )
            lines.append("\n使用 /session resume <序号或ID> 恢复")
            ctx.ui.add_system_message("\n".join(lines))
            ctx.config["_resume_candidates"] = candidates
            return

        candidates = ctx.config.get("_resume_candidates", [])
        if session_id.isdigit():
            idx = int(session_id) - 1
            if candidates and 0 <= idx < len(candidates):
                session_id = candidates[idx]
            else:
                metas = session_manager.list()
                if 0 <= idx < len(metas):
                    session_id = metas[idx].id
                else:
                    ctx.ui.add_system_message(f"序号超出范围: {arg}")
                    return

        result = session_manager.resume(session_id)
        if result is None:
            ctx.ui.add_system_message(f"无法恢复会话: {session_id}")
            return

        if session:
            session.close()

        set_session = ctx.config.get("set_session")
        if set_session:
            set_session(result.session)

        from mewcode.conversation import ConversationManager
        new_conv = ConversationManager()
        new_conv.replace_history(result.messages)

        from mewcode.memory.session import build_time_gap_message
        gap_msg = build_time_gap_message(result.last_active)
        if gap_msg:
            new_conv.add_user_message(gap_msg.content)

        set_conversation = ctx.config.get("set_conversation")
        if set_conversation:
            set_conversation(new_conv)

        if ctx.agent:
            ctx.agent._loop_count = 0

        render_restored = ctx.config.get("render_restored")
        if render_restored:
            render_restored()

        ctx.ui.add_system_message(f"已恢复会话: {session_id}")

    elif cmd == "new":
        if session:
            session.close()
        new_session = session_manager.create()
        set_session = ctx.config.get("set_session")
        if set_session:
            set_session(new_session)

        from mewcode.conversation import ConversationManager
        new_conv = ConversationManager()
        set_conversation = ctx.config.get("set_conversation")
        if set_conversation:
            set_conversation(new_conv)

        if ctx.agent:
            ctx.agent._loop_count = 0

        clear_chat = ctx.config.get("clear_chat")
        if clear_chat:
            clear_chat()

        ctx.ui.add_system_message("已创建新会话")

    elif cmd == "delete":
        if not arg:
            ctx.ui.add_system_message("用法: /session delete <序号或会话ID>")
            return
        delete_id = arg
        try:
            idx = int(arg) - 1
            metas = session_manager.list()
            if 0 <= idx < len(metas):
                delete_id = metas[idx].id
        except ValueError:
            pass
        deleted = session_manager.delete(delete_id)
        if deleted:
            ctx.ui.add_system_message(f"已删除会话: {arg}")
        else:
            ctx.ui.add_system_message(f"会话不存在: {arg}")

    else:
        ctx.ui.add_system_message("用法: /session [list | resume | new | delete]")


SESSION_COMMAND = Command(
    name="session",
    description="会话管理",
    type=CommandType.LOCAL_UI,
    handler=handle_session,
    usage="/session [list | resume <id> | new | delete <id>]",
)