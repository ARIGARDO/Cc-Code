"""Context management: compact circuit breaker, environment injection, auto-compact, result persistence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from mewcode.conversation import ConversationManager


class CompactCircuitBreaker:
    """Prevents compaction from firing too frequently.

    Tracks the number of compaction attempts and the last compaction time.
    Blocks compaction if it was recently attempted.
    """

    def __init__(self) -> None:
        self.attempts = 0
        self.last_compact_time: float = 0.0
        self.max_attempts = 3
        self.cooldown_seconds = 30.0

    def should_allow(self) -> bool:
        import time
        now = time.time()
        if self.attempts >= self.max_attempts:
            if now - self.last_compact_time < self.cooldown_seconds:
                return False
            self.attempts = 0
        return True

    def record_attempt(self) -> None:
        import time
        self.attempts += 1
        self.last_compact_time = time.time()


def inject_environment_context(conversation: ConversationManager, work_dir: str) -> None:
    """Inject environment information (OS, cwd, date) into the conversation."""
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
    """Retrieve long-term memory from the memory manager.

    Returns None if the memory manager is not available or has no entries.
    """
    if memory_manager is None:
        return None
    if hasattr(memory_manager, "get_all_memories"):
        try:
            entries = memory_manager.get_all_memories()
            if entries:
                return "\n".join(entries)
        except Exception:
            pass
    return None


def apply_tool_result_budget(
    conversation: ConversationManager,
    context_window: int,
    circuit_breaker: CompactCircuitBreaker,
) -> bool:
    """Layer 1: Apply budget to tool results to keep context within window.

    Returns True if any changes were made.
    """
    # Layer 1 is a simple budget check; actual compaction is layer 2.
    # For now, this is a no-op that returns False.
    return False


async def auto_compact(
    conversation: ConversationManager,
    client: Any,
    circuit_breaker: CompactCircuitBreaker,
) -> bool:
    """Layer 2: Auto-compact conversation history using LLM summarization.

    Returns True if compaction was performed.
    """
    if not circuit_breaker.should_allow():
        return False
    # For now, auto-compact is a no-op. Future chapters will implement LLM-based compaction.
    return False


def persist_tool_result(output: str, session_dir: Path) -> str:
    """Persist large tool output to a file in session_dir.

    Returns a key that can be used to create a preview.
    """
    import uuid
    key = f"tool_result_{uuid.uuid4().hex[:12]}"
    file_path = session_dir / f"{key}.txt"
    file_path.write_text(output, encoding="utf-8")
    return key


def make_persisted_preview(key: str) -> str:
    """Create a preview message for a persisted tool result."""
    return (
        f"[Large result persisted to localStorage. "
        f"Use ReadFile to fetch the full output: .mewcode/sessions/{key}.txt]\n"
        f"Preview of first 500 chars:\n"
    )