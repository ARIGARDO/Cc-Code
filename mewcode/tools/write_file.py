"""WriteFile — create or overwrite a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult


class Params(BaseModel):
    file_path: str = Field(description="Absolute path to the file to write")
    content: str = Field(description="Content to write to the file")


class WriteFile(Tool):
    name = "WriteFile"
    description = "Create or overwrite a file with the given content."
    params_model = Params
    category = "write"

    def __init__(self, file_cache: Any = None) -> None:
        super().__init__()
        self._cache = file_cache

    async def execute(self, params: Any) -> ToolResult:
        path = Path(params.file_path).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.content, encoding="utf-8")
        except Exception as e:
            return ToolResult(f"Error writing file: {e}", is_error=True)

        if self._cache is not None:
            self._cache.invalidate(path)

        return ToolResult(f"Successfully wrote to {path}")
