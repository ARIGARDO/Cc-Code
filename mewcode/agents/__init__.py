"""mewcode.agents — SubAgent system: definitions, loading, fork, tracing, task management."""

from mewcode.agents.parser import AgentDef, AgentParseError, parse_agent_file, parse_frontmatter
from mewcode.agents.loader import AgentLoader
from mewcode.agents.fork import ForkError, build_forked_messages, FORK_BOILERPLATE, FORK_BOILERPLATE_TAG
from mewcode.agents.tool_filter import resolve_agent_tools, ALL_AGENT_DISALLOWED_TOOLS, ASYNC_AGENT_ALLOWED_TOOLS
from mewcode.agents.trace import TraceManager, TraceNode
from mewcode.agents.task_manager import TaskManager, BackgroundTask, ProgressInfo
from mewcode.agents.notification import format_task_notification, inject_task_notifications

__all__ = [
    "AgentDef",
    "AgentLoader",
    "AgentParseError",
    "ALL_AGENT_DISALLOWED_TOOLS",
    "ASYNC_AGENT_ALLOWED_TOOLS",
    "BackgroundTask",
    "FORK_BOILERPLATE",
    "FORK_BOILERPLATE_TAG",
    "ForkError",
    "ProgressInfo",
    "TaskManager",
    "TraceManager",
    "TraceNode",
    "build_forked_messages",
    "format_task_notification",
    "inject_task_notifications",
    "parse_agent_file",
    "parse_frontmatter",
    "resolve_agent_tools",
]