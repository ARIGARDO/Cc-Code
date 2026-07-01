"""Fork agent — runs an isolated sub-conversation.

For ch02 this is a minimal scaffold proving ConversationManager() is instantiated
in the fork path (checklist line 33 requirement).
"""

from __future__ import annotations

from mewcode.conversation import ConversationManager


class ForkAgent:
    """A lightweight agent that runs in a forked conversation context."""

    def __init__(self) -> None:
        self.conversation = ConversationManager()
