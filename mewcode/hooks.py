"""Hook system for intercepting agent events at 8 lifecycle points.

Provides HookContext, HookNotification, and HookEngine for pre/post processing
of tool execution, turn lifecycle, and session lifecycle events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class HookContext:
    """Context passed to hooks at each lifecycle point."""
    agent_id: str
    event_name: str
    file_path: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result of a pre-tool hook check."""
    accepted: bool = True
    reason: str = ""


@dataclass
class HookNotification:
    """Notification emitted by a hook to be surfaced to the UI."""
    hook_name: str
    message: str


class HookEngine:
    """Manages hooks at 8 lifecycle points:

    session_start, turn_start, pre_send, post_receive,
    pre_tool_use, post_tool_use, turn_end, session_end
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Any]] = {}
        self._notifications: list[HookNotification] = []

    def register(self, event: str, hook: Any) -> None:
        """Register a hook for a specific lifecycle event."""
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(hook)

    def run_hooks_sync(self, event: str, ctx: HookContext) -> None:
        """Run all hooks for an event synchronously (non-blocking, no return)."""
        for hook in self._hooks.get(event, []):
            try:
                hook(ctx)
            except Exception:
                pass

    def run_pre_tool_hooks(self, ctx: HookContext) -> HookResult:
        """Run pre_tool_use hooks that can reject tool execution.

        Returns HookResult(accepted=True) if all hooks pass,
        or HookResult(accepted=False, reason=...) if any hook rejects.
        """
        for hook in self._hooks.get("pre_tool_use", []):
            try:
                result = hook(ctx)
                if isinstance(result, HookResult) and not result.accepted:
                    return result
            except Exception:
                pass
        return HookResult(accepted=True)

    def run_hooks(self, event: str, ctx: HookContext) -> None:
        """Run hooks synchronously (alias for run_hooks_sync)."""
        self.run_hooks_sync(event, ctx)

    def notify(self, hook_name: str, message: str) -> None:
        """Queue a notification to be drained later."""
        self._notifications.append(HookNotification(hook_name=hook_name, message=message))

    def drain_notifications(self) -> list[HookNotification]:
        """Drain and return all pending notifications."""
        result = self._notifications[:]
        self._notifications.clear()
        return result