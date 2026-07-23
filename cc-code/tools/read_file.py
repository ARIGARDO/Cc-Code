"""ReadFile — read a text file with line numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult
from mewcode.tools.ctx import resolve_path


class Params(BaseModel):
    file_path: str = Field(description="Absolute path to the file to read")
    offset: int = Field(default=0, ge=0, description="Line offset (0-based)")
    limit: int = Field(default=2000, ge=1, description="Max lines to read")


class ReadFile(Tool):
    name = "ReadFile"
    description = (
        "Read a text file from the local filesystem. "
        "Returns content with 1-based line numbers in `<line_no>\\t<content>` format. "
        "Use `offset` and `limit` to paginate through large files."
    )
    params_model = Params
    category = "read"
    is_concurrency_safe = True

    def __init__(self, file_cache: Any = None) -> None:
        super().__init__()
        self._cache = file_cache

    async def execute(self, params: Any) -> ToolResult:
        path = Path(resolve_path(params.file_path)).expanduser()
        if not path.exists():
            return ToolResult(f"Error: file not found: {path}", is_error=True)
        if not path.is_file():
            return ToolResult(f"Error: path is not a file: {path}", is_error=True)

        content: Optional[str] = None
        if self._cache is not None:
            content = self._cache.get(path)

        if content is None:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    content = path.read_text(encoding="latin-1")
                except Exception as e:
                    return ToolResult(f"Error reading file: {e}", is_error=True)
            except Exception as e:
                return ToolResult(f"Error reading file: {e}", is_error=True)

            if self._cache is not None:
                self._cache.set(path, content)

        lines = content.splitlines()
        start = params.offset
        end = min(start + params.limit, len(lines))
        if start >= len(lines):
            return ToolResult("", is_error=False)

        out_lines = [f"{i + 1}\t{lines[i]}" for i in range(start, end)]
        return ToolResult("\n".join(out_lines))