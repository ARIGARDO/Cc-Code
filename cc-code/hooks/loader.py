"""Hook loader: parse and validate raw hook configs into Hook objects."""

from __future__ import annotations

import logging
from typing import Any

from mewcode.hooks.events import LifecycleEvent
from mewcode.hooks.models import Action, Hook, HookConfigError
from mewcode.hooks.conditions import parse_condition, ConditionParseError

logger = logging.getLogger(__name__)

_VALID_ACTION_TYPES: frozenset[str] = frozenset(
    {"command", "prompt", "http", "agent"}
)

_REQUIRED_FIELDS: dict[str, str] = {
    "command": "command",
    "prompt": "message",
    "http": "url",
    "agent": "prompt",
}


def load_hooks(raw_hooks: Any) -> list[Hook]:
    """Validate and parse a list of raw hook dicts into ``list[Hook]``.

    Raises ``HookConfigError`` on any invalid configuration.
    """
    if not raw_hooks:
        return []

    hooks: list[Hook] = []
    for i, raw in enumerate(raw_hooks):
        if not isinstance(raw, dict):
            raise HookConfigError(f"hook #{i + 1} must be a mapping")

        hook_id = raw.get("id", "")
        tag = hook_id if hook_id else f"hook #{i + 1}"

        event = raw.get("event", "")
        if event not in LifecycleEvent.__members__:
            raise HookConfigError(
                f"hook '{tag}': invalid event '{event}'"
            )

        action_raw = raw.get("action", {})
        if not isinstance(action_raw, dict):
            raise HookConfigError(
                f"hook '{tag}': action must be a mapping"
            )

        action_type = action_raw.get("type", "")
        if action_type not in _VALID_ACTION_TYPES:
            raise HookConfigError(
                f"hook '{tag}': invalid action type '{action_type}'"
            )

        required_field = _REQUIRED_FIELDS.get(action_type, "")
        if required_field and not action_raw.get(required_field):
            raise HookConfigError(
                f"hook '{tag}': action type '{action_type}' requires '{required_field}' field"
            )

        timeout = action_raw.get("timeout", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            raise HookConfigError(
                f"hook '{tag}': timeout must be a positive integer, got {timeout!r}"
            )

        reject = bool(raw.get("reject", False))
        if reject and event != "pre_tool_use":
            raise HookConfigError(
                f"hook '{tag}': reject=true is only allowed on pre_tool_use event"
            )

        async_exec = bool(raw.get("async", False))
        if async_exec and event == "pre_tool_use":
            raise HookConfigError(
                f"hook '{tag}': async=true is not allowed on pre_tool_use event"
            )

        condition = None
        cond_expr = raw.get("if", "")
        if cond_expr:
            try:
                condition = parse_condition(str(cond_expr))
            except ConditionParseError as e:
                raise HookConfigError(
                    f"hook '{tag}': invalid condition: {e}"
                ) from e

        action = Action(
            type=action_type,
            command=action_raw.get("command", ""),
            message=action_raw.get("message", ""),
            url=action_raw.get("url", ""),
            method=action_raw.get("method", "POST"),
            body=action_raw.get("body", ""),
            headers=dict(action_raw.get("headers", {}) or {}),
            prompt=action_raw.get("prompt", ""),
            timeout=timeout,
        )

        if not hook_id:
            hook_id = f"{event}_{i}"

        hooks.append(
            Hook(
                id=hook_id,
                event=event,
                action=action,
                condition=condition,
                reject=reject,
                once=bool(raw.get("once", False)),
                async_exec=async_exec,
            )
        )

    return hooks