"""Action executors: command, prompt, http, agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mewcode.hooks.models import Action, ActionResult, HookContext

logger = logging.getLogger(__name__)


async def execute_command(action: Action, ctx: HookContext) -> ActionResult:
    cmd = ctx.expand(action.command)
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=action.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ActionResult(
                output=f"Command timed out after {action.timeout}s: {cmd}",
                success=False,
            )
        output = stdout.decode(errors="replace") if stdout else ""
        return ActionResult(output=output.strip(), success=proc.returncode == 0)
    except Exception as e:
        logger.warning("Command hook failed: %s", e)
        return ActionResult(output=str(e), success=False)


async def execute_prompt(action: Action, ctx: HookContext) -> ActionResult:
    message = ctx.expand(action.message)
    return ActionResult(output=message, success=True)


async def execute_http(action: Action, ctx: HookContext) -> ActionResult:
    import urllib.request

    url = ctx.expand(action.url)
    method = action.method.upper() or "POST"
    headers = dict(action.headers) if action.headers else {}

    body_data = None
    if action.body:
        body_data = ctx.expand(action.body).encode("utf-8")
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body_data, headers=headers, method=method)

    def _do_request() -> str:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(500)
            return data.decode(errors="replace")

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _do_request)
        return ActionResult(output=result, success=True)
    except Exception as e:
        logger.warning("HTTP hook failed: %s", e)
        return ActionResult(output=str(e), success=False)


async def execute_agent(action: Action, ctx: HookContext) -> ActionResult:
    logger.debug("Agent action type is a stub, not yet implemented")
    return ActionResult(output="agent executor not yet implemented", success=True)


_EXECUTOR_MAP: dict[str, Any] = {
    "command": execute_command,
    "prompt": execute_prompt,
    "http": execute_http,
    "agent": execute_agent,
}


async def execute_action(action: Action, ctx: HookContext) -> ActionResult:
    executor = _EXECUTOR_MAP.get(action.type)
    if executor is None:
        return ActionResult(output=f"Unknown action type: {action.type}", success=False)
    return await executor(action, ctx)