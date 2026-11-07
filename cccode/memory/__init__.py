"""Memory management for long-term context retention."""

from cccode.memory.auto_memory import MemoryManager, should_trigger_extraction
from cccode.memory.instructions import load_instructions, process_includes
from cccode.memory.session import (
    ResumeResult,
    Session,
    SessionManager,
    SessionMeta,
    SessionRecord,
    build_time_gap_message,
    generate_session_summary,
    validate_message_chain,
)

__all__ = [
    "MemoryManager",
    "should_trigger_extraction",
    "load_instructions",
    "process_includes",
    "ResumeResult",
    "Session",
    "SessionManager",
    "SessionMeta",
    "SessionRecord",
    "build_time_gap_message",
    "generate_session_summary",
    "validate_message_chain",
]