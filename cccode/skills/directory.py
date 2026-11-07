"""Directory skill support: tool.json parsing, dynamic tool loading, registration."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from cccode.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


def parse_tool_json(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to parse tool.json at %s: %s", path, e)
        return []
    if isinstance(data, dict):
        if "tools" in data:
            tools = data["tools"]
        else:
            tools = [data]
    elif isinstance(data, list):
        tools = data
    else:
        logger.warning("Unexpected tool.json format at %s", path)
        return []
    return tools if isinstance(tools, list) else [tools]


def load_tool_implementation(references_dir: Path, tool_name: str) -> Callable | None:
    py_file = references_dir / f"{tool_name}.py"
    if not py_file.is_file():
        logger.warning("Tool implementation not found: %s", py_file)
        return None
    try:
        module_name = f"cccode_skill_tool_{tool_name}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "execute", None)
    except Exception as e:
        logger.warning("Failed to load tool implementation '%s': %s", tool_name, e)
        return None


class _DynamicParams(BaseModel):
    model_config = {"extra": "allow"}


class SkillCustomTool(Tool):
    name: str = ""
    description: str = ""
    params_model: type[Any] = _DynamicParams
    category: str = "read"
    is_concurrency_safe: bool = False

    def __init__(self, tool_name: str, description: str, schema: dict, impl: Callable | None) -> None:
        super().__init__()
        self.name = tool_name
        self.description = description
        self._schema = schema
        self._impl = impl

    def get_schema(self) -> dict[str, Any]:
        params = self._schema.get("parameters") or self._schema.get("input_schema")
        if params:
            return params
        return super().get_schema()

    async def execute(self, params: Any) -> ToolResult:
        if self._impl is None:
            return ToolResult(output=f"Tool '{self.name}' has no implementation", is_error=True)
        try:
            kwargs = {}
            if hasattr(params, "model_dump"):
                kwargs = params.model_dump()
            elif isinstance(params, dict):
                kwargs = params
            if asyncio.iscoroutinefunction(self._impl):
                result = await self._impl(**kwargs)
            else:
                result = self._impl(**kwargs)
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"Tool '{self.name}' error: {e}", is_error=True)


def register_skill_tools(skill_dir: Path, registry: Any) -> int:
    tool_json_path = skill_dir / "tool.json"
    schemas = parse_tool_json(tool_json_path)
    if not schemas:
        return 0

    references_dir = skill_dir / "references"
    count = 0

    for schema in schemas:
        tool_name = schema.get("name", "")
        if not tool_name:
            continue
        if registry.get(tool_name) is not None:
            logger.debug("Tool '%s' already registered, skipping", tool_name)
            continue
        desc = schema.get("description", "")
        impl = load_tool_implementation(references_dir, tool_name)
        custom_tool = SkillCustomTool(
            tool_name=tool_name,
            description=desc,
            schema=schema,
            impl=impl,
        )
        registry.register(custom_tool)
        count += 1

    return count