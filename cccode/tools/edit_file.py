"""EditFile — unique-string replace in a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cccode.tools.base import Tool, ToolResult
from cccode.tools.ctx import resolve_path


class Params(BaseModel):
    file_path: str = Field(description="Absolute path to the file to edit")
    old_string: str = Field(description="Exact string to replace (must be unique)")
    new_string: str = Field(description="Replacement string")


class EditFile(Tool):
    name = "EditFile"
    description = (
        "Perform exact string replacement in an existing file. "
        "`old_string` must match exactly once in the file."
    )
    params_model = Params
    category = "write"

    def __init__(self, file_cache: Any = None) -> None:
        super().__init__()
        self._cache = file_cache

    async def execute(self, params: Any) -> ToolResult:
        path = Path(resolve_path(params.file_path)).expanduser()
        if not path.exists():
            return ToolResult(f"Error: file not found: {path}", is_error=True)
        if not path.is_file():
            return ToolResult(f"Error: path is not a file: {path}", is_error=True)

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(f"Error reading file: {e}", is_error=True)

        count = content.count(params.old_string)
        if count == 0:
            return ToolResult(
                f"Error: old_string not found in {path}.", is_error=True
            )
        if count > 1:
            return ToolResult(
                f"Error: old_string found {count} times in {path}, must be unique.",
                is_error=True,
            )

        new_content = content.replace(params.old_string, params.new_string, 1)
        try:
            path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return ToolResult(f"Error writing file: {e}", is_error=True)

        if self._cache is not None:
            self._cache.invalidate(path)

        return ToolResult(f"Successfully edited {path}")