"""Glob — find files matching a glob pattern."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cccode.tools.base import SKIP_DIRS, Tool, ToolResult
from cccode.tools.ctx import resolve_path


class Params(BaseModel):
    pattern: str = Field(description="Glob pattern (e.g. '**/*.py')")
    path: str = Field(default=".", description="Base directory for the search")


class Glob(Tool):
    name = "Glob"
    description = (
        "Find files matching a glob pattern. Returns paths sorted alphabetically, "
        "one per line, relative to the search directory. Skips common VCS/dependency dirs."
    )
    params_model = Params
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: Any) -> ToolResult:
        base = Path(resolve_path(params.path)).expanduser()
        if not base.is_dir():
            return ToolResult(f"Error: not a directory: {base}", is_error=True)
        pattern = Path(params.pattern)
        if pattern.is_absolute() or ".." in pattern.parts:
            return ToolResult("Error: pattern must stay within the search directory", is_error=True)

        results: list[str] = []
        for p in base.glob(params.pattern):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.resolve().is_relative_to(base.resolve()):
                results.append(str(p.relative_to(base)))

        results.sort()
        if not results:
            return ToolResult("No files matched the pattern.")
        return ToolResult("\n".join(results))
