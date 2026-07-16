"""AgentTool — spawn a sub-agent with model override, fork, and background support."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from mewcode.agents.parser import AgentDef
from mewcode.agents.fork import ForkError, build_forked_messages
from mewcode.agents.tool_filter import resolve_agent_tools
from mewcode.agents.trace import TraceManager
from mewcode.agents.task_manager import TaskManager
from mewcode.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class AgentToolParams(BaseModel):
    prompt: str = Field(..., description="The task prompt for the sub-agent")
    description: str = Field(..., description="Short description of what the sub-agent will do")
    subagent_type: str = Field("", description="Built-in or custom agent type to use")
    model: str = Field("", description="Model override: haiku, sonnet, opus, or inherit")
    run_in_background: bool = Field(False, description="Run the sub-agent in the background")
    name: str = Field("", description="Name for team scenario identification")
    isolation: str = Field("", description="Isolation mode: worktree")
    team_name: str = Field("", description="Team name for long-running teammate")


PERMISSION_MODE_MAP: dict[str, Any] = {}

TEAMMATE_ADDENDUM = (
    "You are running as an agent in a team. "
    "You can communicate with other team members using SendMessage. "
    "You can create and manage tasks using TaskCreate, TaskGet, TaskList, and TaskUpdate."
)

MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6-20250514",
    "opus": "claude-opus-4-6-20250514",
}


def _create_client_for_model(
    model_alias: str,
    parent_config: Any,
) -> Any:
    """Build a child LLMClient for *model_alias* inheriting parent config."""
    from mewcode.config import ProviderConfig as PC
    from mewcode.client import create_client

    resolved_model = MODEL_MAP.get(model_alias, model_alias)
    child_config = PC(
        name=parent_config.name,
        protocol=parent_config.protocol,
        base_url=parent_config.base_url,
        api_key=parent_config.api_key,
        model=resolved_model,
        thinking=parent_config.thinking,
    )
    return create_client(child_config)


class AgentTool(Tool):
    """Spawn a sub-agent to handle a task in an isolated context."""

    name = "Agent"
    description = "Spawn a sub-agent to handle a task"
    params_model = AgentToolParams
    category = "command"
    is_concurrency_safe = False

    def __init__(
        self,
        agent_loader: Any = None,
        task_manager: TaskManager | None = None,
        trace_manager: TraceManager | None = None,
        parent_agent: Any = None,
        enable_fork: bool = False,
        provider_config: Any = None,
        worktree_manager: Any = None,
        team_manager: Any = None,
    ) -> None:
        self._agent_loader = agent_loader
        self._task_manager = task_manager or TaskManager()
        self._trace_manager = trace_manager or TraceManager()
        self._parent_agent = parent_agent
        self._enable_fork = enable_fork
        self._provider_config = provider_config
        self._worktree_manager = worktree_manager
        self._team_manager = team_manager

    def _select_llm(self, params: AgentToolParams, definition: AgentDef | None) -> Any:
        """Select the LLM client: params.model > definition.model > parent."""
        model = params.model
        if not model and definition and definition.model != "inherit":
            model = definition.model

        if model and model != "inherit":
            try:
                client = _create_client_for_model(model, self._provider_config)
                if client:
                    return client
            except Exception as e:
                logger.warning("Failed to create client for model '%s': %s", model, e)

        if self._parent_agent and hasattr(self._parent_agent, "client"):
            return self._parent_agent.client

        from mewcode.client import create_client
        return create_client(self._provider_config)

    async def execute(self, params: Any) -> ToolResult:
        """Execute the Agent tool — dispatch to the appropriate path."""
        p = AgentToolParams(**params) if isinstance(params, dict) else params

        if p.team_name:
            return await self._execute_as_teammate(p)

        if p.isolation == "worktree":
            return await self._execute_with_worktree(p)

        if not p.subagent_type:
            if self._enable_fork:
                return await self._execute_fork(p)
            return ToolResult(
                output="Error: no subagent_type specified and fork is not enabled. "
                       "Provide a subagent_type or enable fork mode.",
                is_error=True,
            )

        definition = None
        if self._agent_loader:
            definition = self._agent_loader.get(p.subagent_type)

        if definition is None:
            available = []
            if self._agent_loader:
                available = [a[0] for a in self._agent_loader.list_agents()]
            return ToolResult(
                output=f"Error: unknown agent type '{p.subagent_type}'. "
                       f"Available types: {available}",
                is_error=True,
            )

        is_background = p.run_in_background or definition.background

        return await self._execute_sub_agent(p, definition, is_background)

    async def _execute_sub_agent(
        self,
        params: AgentToolParams,
        definition: AgentDef,
        is_background: bool,
    ) -> ToolResult:
        """Execute a sub-agent with the given definition."""
        from mewcode.agent import Agent
        from mewcode.permissions.modes import PermissionMode

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=getattr(self._parent_agent, "agent_id", ""),
        )

        client = self._select_llm(params, definition)

        allowed_tools = resolve_agent_tools(
            self._parent_agent.registry if self._parent_agent else None,
            definition,
            is_background=is_background,
        )

        pm = PermissionMode.DEFAULT
        if definition.permission_mode and PERMISSION_MODE_MAP:
            pm = PERMISSION_MODE_MAP.get(definition.permission_mode, PermissionMode.DEFAULT)

        try:
            sub_agent = Agent(
                client=client,
                registry=self._parent_agent.registry if self._parent_agent else None,
                protocol=getattr(self._parent_agent, "protocol", "anthropic"),
                work_dir=getattr(self._parent_agent, "_work_dir", None),
                max_turns=definition.max_turns,
                system_prompt=definition.system_prompt,
                allowed_tools=allowed_tools,
                permission_mode=pm,
            )

            if is_background:
                task_id = self._task_manager.launch(
                    sub_agent.run_to_completion(params.prompt),
                    agent_type=definition.agent_type,
                )
                return ToolResult(
                    output=f"Task ID: {task_id}\nAgent type: {definition.agent_type} is running in the background."
                )

            result = await sub_agent.run_to_completion(params.prompt)
            self._trace_manager.complete(trace_node.agent_id, "completed")
            return ToolResult(output=result)

        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            logger.warning("Sub-agent execution failed: %s", e)
            return ToolResult(output=f"Sub-agent error: {e}", is_error=True)

    async def _execute_fork(self, params: AgentToolParams) -> ToolResult:
        """Execute a forked sub-agent from the parent conversation."""
        if not self._parent_agent:
            return ToolResult(output="Error: no parent agent for fork", is_error=True)

        try:
            conversation = getattr(self._parent_agent, "conversation", None)
            if conversation is None:
                return ToolResult(output="Error: no parent conversation", is_error=True)

            forked_conv = build_forked_messages(conversation, params.prompt)

        except ForkError as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

        from mewcode.agent import Agent

        trace_node = self._trace_manager.create(
            agent_type="fork",
            parent_id=getattr(self._parent_agent, "agent_id", ""),
        )

        client = self._select_llm(params, None)

        try:
            sub_agent = Agent(
                client=client,
                registry=self._parent_agent.registry,
                protocol=getattr(self._parent_agent, "protocol", "anthropic"),
                work_dir=getattr(self._parent_agent, "_work_dir", None),
                system_prompt="",
                conversation=forked_conv,
            )

            task_id = self._task_manager.launch(
                sub_agent.run_to_completion(params.prompt),
                agent_type="fork",
            )
            return ToolResult(
                output=f"Task ID: {task_id}\nForked agent is running in the background."
            )

        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(output=f"Fork error: {e}", is_error=True)

    async def _execute_with_worktree(self, params: AgentToolParams) -> ToolResult:
        """Execute a sub-agent in an isolated git worktree."""
        if self._worktree_manager is None:
            return ToolResult(
                output="Error: worktree isolation requested but WorktreeManager is not available",
                is_error=True,
            )

        definition = None
        if params.subagent_type and self._agent_loader:
            definition = self._agent_loader.get(params.subagent_type)

        if definition is None:
            definition = AgentDef(agent_type=params.subagent_type or "general-purpose")

        from mewcode.worktree.sweep import random_agent_name
        from mewcode.tools.ctx import with_cwd
        from pathlib import Path

        name = random_agent_name()
        try:
            wt = await self._worktree_manager.create(name, "HEAD", manual=False)
        except Exception as e:
            return ToolResult(output=f"Error creating worktree: {e}", is_error=True)

        parent_cwd = str(Path.cwd())
        notice = build_worktree_notice(parent_cwd, wt.path)
        task_text = notice + "\n\n" + params.prompt

        from mewcode.agent import Agent
        from mewcode.permissions.modes import PermissionMode

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=getattr(self._parent_agent, "agent_id", ""),
        )

        client = self._select_llm(params, definition)

        allowed_tools = resolve_agent_tools(
            self._parent_agent.registry if self._parent_agent else None,
            definition,
            is_background=False,
        )

        pm = PermissionMode.DEFAULT
        if definition.permission_mode and PERMISSION_MODE_MAP:
            pm = PERMISSION_MODE_MAP.get(definition.permission_mode, PermissionMode.DEFAULT)

        try:
            sub_agent = Agent(
                client=client,
                registry=self._parent_agent.registry if self._parent_agent else None,
                protocol=getattr(self._parent_agent, "protocol", "anthropic"),
                work_dir=wt.path,
                max_turns=definition.max_turns,
                system_prompt=definition.system_prompt,
                allowed_tools=allowed_tools,
                permission_mode=pm,
            )

            with with_cwd(wt.path):
                result = await sub_agent.run_to_completion(task_text)

            self._trace_manager.complete(trace_node.agent_id, "completed")

            report = await self._worktree_manager.auto_cleanup(name)
            if report.kept:
                result += f"\n[Worktree 保留在 {report.path}, 分支 {report.branch}]"

            return ToolResult(output=result)

        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            logger.warning("Worktree agent execution failed: %s", e)
            return ToolResult(output=f"Worktree agent error: {e}", is_error=True)

    async def _execute_as_teammate(self, params: AgentToolParams) -> ToolResult:
        """Execute as a team member (ch15 integration stub)."""
        if self._team_manager is None:
            return ToolResult(
                output="Error: team mode requested but TeamManager is not available",
                is_error=True,
            )

        definition = None
        if params.subagent_type and self._agent_loader:
            definition = self._agent_loader.get(params.subagent_type)

        if definition is None:
            from mewcode.agents.parser import AgentDef
            definition = AgentDef(agent_type=params.name or "teammate")

        system_prompt = definition.system_prompt
        if system_prompt:
            system_prompt += "\n\n" + TEAMMATE_ADDENDUM
        else:
            system_prompt = TEAMMATE_ADDENDUM

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=getattr(self._parent_agent, "agent_id", ""),
        )

        client = self._select_llm(params, definition)

        try:
            from mewcode.agent import Agent
            sub_agent = Agent(
                client=client,
                registry=self._parent_agent.registry if self._parent_agent else None,
                protocol=getattr(self._parent_agent, "protocol", "anthropic"),
                work_dir=getattr(self._parent_agent, "_work_dir", None),
                max_turns=definition.max_turns,
                system_prompt=system_prompt,
            )

            task_id = self._task_manager.launch(
                sub_agent.run_to_completion(params.prompt),
                agent_type=definition.agent_type,
            )
            return ToolResult(
                output=f"Task ID: {task_id}\nTeammate '{definition.agent_type}' is running in the background."
            )

        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(output=f"Teammate error: {e}", is_error=True)


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """Build a worktree context notice to prepend to the sub-agent's task prompt."""
    return (
        "<worktree-context>\n"
        "你当前在一个独立的 Git Worktree 副本中工作,与父 Agent 隔离。\n"
        f"- 父目录: {parent_cwd}\n"
        f"- 你的工作目录: {wt_path}\n"
        "- 父 Agent 提到的绝对路径基于父目录,你需要翻译成本地路径(替换前缀)再读写\n"
        "- 编辑文件前,必须先在本地 Worktree 重新 read_file 一次,避免使用过时内容\n"
        "</worktree-context>"
    )