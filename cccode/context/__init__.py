"""Context management package — re-exports for convenience."""

import os
from typing import Any, Optional

from cccode.conversation import ConversationManager

from cccode.context.manager import (
    AGGREGATE_CHAR_LIMIT,
    AUTO_COMPACT_SAFETY_MARGIN,
    MANUAL_COMPACT_SAFETY_MARGIN,
    PERSISTED_TAG,
    PREVIEW_CHARS,
    SESSION_SUBDIR,
    SINGLE_RESULT_CHAR_LIMIT,
    SNIPPED_TAG,
    SUMMARY_OUTPUT_RESERVE,
    CompactCircuitBreaker,
    CompactEvent,
    ContentReplacementRecord,
    ContentReplacementState,
    FileReadRecord,
    RecoveryState,
    SkillInvocationRecord,
    append_replacement_records,
    apply_tool_result_budget,
    auto_compact,
    build_compact_messages,
    build_recovery_attachment,
    cleanup_tool_results,
    clone_replacement_state,
    compute_compact_threshold,
    create_replacement_state,
    ensure_session_dir,
    extract_summary,
    load_replacement_records,
    make_persisted_preview,
    manual_compact,
    persist_tool_result,
    reconstruct_replacement_state,
    should_auto_compact,
)


def inject_environment_context(
    conversation: ConversationManager, work_dir: str
) -> None:
    import datetime
    import platform

    env = f"""<env>
Operating system: {platform.system()}
Working directories:
{os.path.abspath(work_dir)}
Today's date: {datetime.date.today().isoformat()}
</env>"""
    conversation.inject_environment(env)


def get_long_term_memory(memory_manager: Any) -> Optional[str]:
    if memory_manager is None:
        return None
    if hasattr(memory_manager, "load"):
        try:
            content = memory_manager.load()
            if content:
                return content
        except Exception:
            pass
    if hasattr(memory_manager, "get_all_memories"):
        try:
            entries = memory_manager.get_all_memories()
            if entries:
                return "\n".join(entries)
        except Exception:
            pass
    return None


__all__ = [
    "AGGREGATE_CHAR_LIMIT",
    "AUTO_COMPACT_SAFETY_MARGIN",
    "MANUAL_COMPACT_SAFETY_MARGIN",
    "PERSISTED_TAG",
    "PREVIEW_CHARS",
    "SESSION_SUBDIR",
    "SINGLE_RESULT_CHAR_LIMIT",
    "SNIPPED_TAG",
    "SUMMARY_OUTPUT_RESERVE",
    "CompactCircuitBreaker",
    "CompactEvent",
    "ContentReplacementRecord",
    "ContentReplacementState",
    "FileReadRecord",
    "RecoveryState",
    "SkillInvocationRecord",
    "append_replacement_records",
    "apply_tool_result_budget",
    "auto_compact",
    "build_compact_messages",
    "build_recovery_attachment",
    "cleanup_tool_results",
    "clone_replacement_state",
    "compute_compact_threshold",
    "create_replacement_state",
    "ensure_session_dir",
    "extract_summary",
    "get_long_term_memory",
    "inject_environment_context",
    "load_replacement_records",
    "make_persisted_preview",
    "manual_compact",
    "persist_tool_result",
    "reconstruct_replacement_state",
    "should_auto_compact",
]