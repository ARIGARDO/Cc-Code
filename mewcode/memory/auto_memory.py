"""Automatic memory extraction from conversation history."""

from __future__ import annotations

from typing import Any

from mewcode.conversation import ConversationManager


def extract_and_store_memory(
    memory_manager: Any,
    conversation: ConversationManager,
) -> None:
    """Extract key facts from the conversation and store them in long-term memory.

    Called periodically (every MEMORY_EXTRACTION_INTERVAL iterations).
    For now, this is a stub until the full memory system is implemented.
    """
    if memory_manager is None:
        return
    # Future: use LLM to extract key facts from conversation history
    pass