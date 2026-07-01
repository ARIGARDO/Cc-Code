"""Skill executor — runs skills in isolated fork agents.

For ch02 this is a minimal scaffold: the wiring point where
ConversationManager() is instantiated for skill contexts.
"""

from __future__ import annotations


class SkillExecutor:
    """Executes a skill inside a forked conversation context."""

    def __init__(self) -> None:
        from mewcode.conversation import ConversationManager
        self._conversation = ConversationManager()
