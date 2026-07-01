"""Bash — run a shell command with timeout."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

MAX_TIMEOUT = 600


class Params(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(
        default=120, ge=1, le=MAX_TIMEOUT, description="Timeout in seconds"
    )


class Bash(Tool):
    name = "Bash"
    description = (
        "Execute a shell command in a subprocess. "
        "Returns STDOUT, STDERR, and exit code. "
        f"Maximum timeout is {MAX_TIMEOUT}s."
    )
    params_model = Params
    category = "command"

    async def execute(self, params: Any) -> ToolResult:
        effective_timeout = min(params.timeout, MAX_TIMEOUT)
        try:
            proc = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            return ToolResult(
                f"Error: command timed out after {effective_timeout}s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(f"Error executing command: {e}", is_error=True)

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        parts: list[str] = []
        if stdout:
            parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            parts.append(f"STDERR:\n{stderr}")
        if not parts:
            parts.append("(no output)")

        output = "\n".join(parts)
        is_error = proc.returncode != 0
        return ToolResult(output, is_error=is_error)
