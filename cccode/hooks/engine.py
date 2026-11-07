"""HookEngine: core hook matching, execution, and notification draining."""

from __future__ import annotations

import asyncio
import logging

from cccode.hooks.models import (
    Hook,
    HookContext,
    HookNotification,
    ToolRejectedError,
)
from cccode.hooks.executors import execute_action

logger = logging.getLogger(__name__)


class HookEngine:
    """Central hook engine that matches, runs, and manages hooks."""

    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self.hooks: list[Hook] = list(hooks) if hooks else []
        self._prompt_messages: list[str] = []
        self._notifications: list[HookNotification] = []

    def find_matching_hooks(
        self, event: str, ctx: HookContext
    ) -> list[Hook]:
        """Return hooks that match *event* and pass should_run + condition."""
        matched: list[Hook] = []
        for hook in self.hooks:
            if hook.event != event:
                continue
            if not hook.should_run():
                continue
            if hook.condition is not None:
                try:
                    if not hook.condition.evaluate(ctx):
                        continue
                except Exception:
                    logger.warning(
                        "Condition evaluation failed for hook '%s'; skipping",
                        hook.id,
                    )
                    continue
            matched.append(hook)
        return matched

    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        """Run all hooks matching *event*.

        - ``async_exec=True`` hooks are dispatched via
          ``asyncio.ensure_future`` and not awaited.
        - All other hooks are awaited sequentially.
        """
        matched = self.find_matching_hooks(event, ctx)
        for hook in matched:
            if hook.async_exec:
                asyncio.ensure_future(self._run_single(hook, ctx))
            else:
                await self._run_single(hook, ctx)

    async def _run_single(self, hook: Hook, ctx: HookContext) -> None:
        """Execute a single hook, record result, and mark executed."""
        try:
            result = await execute_action(hook.action, ctx)
            if result.success and hook.action.type == "prompt":
                self._prompt_messages.append(result.output)
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=result.output,
                    success=result.success,
                )
            )
        except Exception as e:
            logger.warning("Hook '%s' execution failed: %s", hook.id, e)
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=str(e),
                    success=False,
                )
            )
        finally:
            hook.mark_executed()

    async def run_pre_tool_hooks(
        self, ctx: HookContext
    ) -> ToolRejectedError | None:
        """Run ``pre_tool_use`` hooks sequentially.

        If any hook with ``reject=True`` matches and succeeds, return a
        ``ToolRejectedError``.  Returns ``None`` when the tool call is
        allowed to proceed.
        """
        matched = self.find_matching_hooks("pre_tool_use", ctx)
        for hook in matched:
            try:
                result = await execute_action(hook.action, ctx)
                hook.mark_executed()
                if hook.reject and result.success:
                    return ToolRejectedError(
                        tool=ctx.tool_name,
                        reason=result.output,
                        hook_id=hook.id,
                    )
                self._notifications.append(
                    HookNotification(
                        hook_id=hook.id,
                        event=hook.event,
                        output=result.output,
                        success=result.success,
                    )
                )
            except Exception as e:
                logger.warning(
                    "pre_tool_use hook '%s' failed: %s", hook.id, e
                )
                self._notifications.append(
                    HookNotification(
                        hook_id=hook.id,
                        event=hook.event,
                        output=str(e),
                        success=False,
                    )
                )
                hook.mark_executed()
        return None

    def get_prompt_messages(self) -> list[str]:
        """Return accumulated prompt messages and clear the buffer."""
        msgs = list(self._prompt_messages)
        self._prompt_messages.clear()
        return msgs

    def drain_notifications(self) -> list[HookNotification]:
        """Return all pending notifications and clear the buffer."""
        notes = list(self._notifications)
        self._notifications.clear()
        return notes