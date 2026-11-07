"""Skill executor: inline/fork execution, tool filtering, dependency errors."""

from __future__ import annotations

import logging
from typing import Any

from cccode.skills.parser import SkillDef, substitute_arguments

logger = logging.getLogger(__name__)

SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})


class SkillDependencyError(Exception):
    pass


def filter_tool_registry(registry: Any, allowed: list[str]) -> Any:
    if not allowed:
        return registry
    from cccode.tools import ToolRegistry
    new_registry = ToolRegistry()
    allowed_set = set(allowed)
    for name in registry.list_tools():
        tool = registry.get(name)
        if tool is None:
            continue
        if getattr(tool, "is_system_tool", False):
            new_registry.register(tool)
            continue
        if name in allowed_set:
            new_registry.register(tool)
    missing = allowed_set - set(new_registry.list_tools())
    if missing:
        raise SkillDependencyError(f"missing tools: {', '.join(sorted(missing))}")
    return new_registry


class SkillExecutor:
    def __init__(self, agent: Any, client: Any = None, protocol: str = "anthropic") -> None:
        self.agent = agent
        self.client = client
        self.protocol = protocol

    def _ensure_skill_tools(self, skill: SkillDef) -> int:
        if not skill.is_directory or skill.source_path is None:
            return 0
        try:
            from cccode.skills.directory import register_skill_tools
            skill_dir = skill.source_path.parent
            return register_skill_tools(skill_dir, self.agent.registry)
        except Exception as e:
            logger.warning("Failed to register skill tools for '%s': %s", skill.name, e)
            return 0

    async def execute_inline(self, skill: SkillDef, args: str = "") -> None:
        self._ensure_skill_tools(skill)
        rendered = substitute_arguments(skill.prompt_body, args)
        self.agent.activate_skill(skill.name, rendered)

    async def execute_fork(self, skill: SkillDef, args: str = "") -> str:
        self._ensure_skill_tools(skill)
        rendered = substitute_arguments(skill.prompt_body, args)

        from cccode.conversation import ConversationManager
        fork_conv = ConversationManager()

        if skill.context == "recent":
            main_conv = getattr(self.agent, "_conversation", None)
            if main_conv:
                recent = [
                    m for m in main_conv.history
                    if m.role in ("user", "assistant")
                ][-5:]
                for msg in recent:
                    fork_conv.add_user_message(msg.content) if msg.role == "user" else fork_conv.history.append(msg)
        elif skill.context == "full":
            main_conv = getattr(self.agent, "_conversation", None)
            if main_conv:
                summary_lines = []
                for msg in main_conv.history:
                    if msg.role in ("user", "assistant") and msg.content:
                        summary_lines.append(f"{msg.role}: {msg.content[:200]}")
                if summary_lines:
                    fork_conv.add_user_message(
                        "## Previous conversation summary\n\n" + "\n".join(summary_lines)
                    )

        fork_conv.add_user_message(rendered)

        try:
            fork_registry = filter_tool_registry(self.agent.registry, skill.allowed_tools)
        except SkillDependencyError as e:
            return f"Skill dependency error: {e}"

        from cccode.agent import Agent as AgentClass, StreamText, LoopComplete, ErrorEvent

        fork_agent = AgentClass(
            client=self.client,
            protocol=self.protocol,
            registry=fork_registry,
            work_dir=getattr(self.agent, "work_dir", "."),
            max_iterations=getattr(self.agent, "max_iterations", 20),
            context_window=getattr(self.agent, "context_window", 200000),
        )

        result_parts: list[str] = []
        try:
            async for event in fork_agent.run(fork_conv):
                if isinstance(event, StreamText):
                    result_parts.append(event.text)
                elif isinstance(event, ErrorEvent):
                    result_parts.append(f"\n[ERROR] {event.message}\n")
                elif isinstance(event, LoopComplete):
                    break
        except Exception as e:
            result_parts.append(f"\n[FORK ERROR] {e}\n")

        return "".join(result_parts)