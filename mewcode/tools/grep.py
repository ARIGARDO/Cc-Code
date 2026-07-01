"""Grep — search files with a regex pattern."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mewcode.tools.base import SKIP_DIRS, Tool, ToolResult


class Params(BaseModel):
    pattern: str = Field(description="Regular expression to search for")
    path: str = Field(default=".", description="Base directory for the search")
    include: str = Field(
        default="", description="Optional glob filter for file names (e.g. '*.py')"
    )


class Grep(Tool):
    name = "Grep"
    description = (
        "Search files for lines matching a regex pattern. "
        "Returns matches in `<rel_path>:<line_num>:<line>` format. "
        "Use `include` to filter by file extension or name glob."
    )
    params_model = Params
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: Any) -> ToolResult:
        try:
            regex = re.compile(params.pattern)
        except re.error as e:
            return ToolResult(f"Error: invalid regex pattern: {e}", is_error=True)

        base = Path(params.path).expanduser().resolve()
        if not base.is_dir():
            return ToolResult(f"Error: not a directory: {base}", is_error=True)

        include_glob = params.include.strip() if params.include else None
        results: list[str] = []

        for p in base.rglob("*"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if not p.is_file():
                continue
            if include_glob is not None and not p.match(include_glob):
                continue
            try:
                for line_no, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if regex.search(line):
                        rel = str(p.relative_to(base))
                        results.append(f"{rel}:{line_no}:{line}")
            except Exception:
                continue

        if not results:
            return ToolResult("No matches found.")
        return ToolResult("\n".join(results))
