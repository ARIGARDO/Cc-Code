"""Skill executor — runs skills in isolated fork agents.

For ch02 this is a minimal scaffold: the wiring point where
ConversationManager() is instantiated for skill contexts.
"""

from __future__ import annotations

from typing import Any


class SkillExecutor:
    """Executes a skill inside a forked conversation context."""

    def __init__(self, agent: Any = None) -> None:
        from mewcode.conversation import ConversationManager
        self._conversation = ConversationManager()
        self.agent = agent

    def _record_skill(self, name: str, body: str) -> None:
        rs = getattr(self.agent, "recovery_state", None) if self.agent else None
        if rs is not None:
            rs.record_skill_invocation(name, body)

    async def execute_inline(self, skill: Any, prompt: str) -> Any:
        self._record_skill(skill.name, prompt)
        if self.agent and hasattr(self.agent, "activate_skill"):
            self.agent.activate_skill(skill)
        return None

    async def execute_fork(self, skill: Any, arguments: dict[str, Any] | None = None) -> Any:
        body = getattr(skill, "prompt_body", "")
        self._record_skill(skill.name, body)
        return None