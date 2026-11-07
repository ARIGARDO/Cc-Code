"""cccode.hooks — Hook system for lifecycle events, conditions, and actions."""

from cccode.hooks.events import LifecycleEvent
from cccode.hooks.models import (
    Action,
    ActionResult,
    Hook,
    HookConfigError,
    HookContext,
    HookNotification,
    ToolRejectedError,
)
from cccode.hooks.conditions import (
    Condition,
    ConditionGroup,
    ConditionParseError,
    parse_condition,
)
from cccode.hooks.engine import HookEngine
from cccode.hooks.loader import load_hooks

__all__ = [
    "Action",
    "ActionResult",
    "Condition",
    "ConditionGroup",
    "ConditionParseError",
    "Hook",
    "HookConfigError",
    "HookContext",
    "HookEngine",
    "HookNotification",
    "LifecycleEvent",
    "ToolRejectedError",
    "load_hooks",
    "parse_condition",
]