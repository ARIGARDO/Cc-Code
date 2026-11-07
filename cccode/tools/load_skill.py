"""LoadSkill tool: on-demand skill activation by the agent."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from cccode.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class LoadSkillParams(BaseModel):
    name: str


class LoadSkill(Tool):
    name: str = "LoadSkill"
    description: str = "Activate a skill by name. Loads the skill's SOP into the environment context and registers any specialized tools."
    params_model: type[Any] = LoadSkillParams
    category: str = "read"
    is_concurrency_safe: bool = False
    is_system_tool: bool = True

    _loader: Any = None
    _agent: Any = None

    def set_loader(self, loader: Any) -> None:
        self._loader = loader

    def set_agent(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, params: Any) -> ToolResult:
        if self._loader is None or self._agent is None:
            return ToolResult(
                output="LoadSkill not properly initialized",
                is_error=True,
            )

        skill_name = params.name if hasattr(params, "name") else str(params)
        skill = self._loader.get(skill_name)
        if skill is None:
            catalog = self._loader.get_catalog()
            available = ", ".join(f"'{n}'" for n, _ in catalog)
            return ToolResult(
                output=f"Skill '{skill_name}' not found. Available skills: {available}",
                is_error=True,
            )

        self._agent.activate_skill(skill.name, skill.prompt_body)

        tool_count = 0
        if skill.is_directory and skill.source_path is not None:
            try:
                from cccode.skills.directory import register_skill_tools
                skill_dir = skill.source_path.parent
                tool_count = register_skill_tools(skill_dir, self._agent.registry)
            except Exception as e:
                logger.warning("Failed to register skill tools for '%s': %s", skill_name, e)

        msg = f"Skill '{skill.name}' activated. SOP pinned to environment context."
        if tool_count > 0:
            msg += f" {tool_count} specialized tool(s) registered."
        return ToolResult(output=msg)