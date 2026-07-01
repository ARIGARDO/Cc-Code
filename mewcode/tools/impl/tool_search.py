"""ToolSearch — discover deferred tools by name or keyword."""

from __future__ import annotations

import json as _json
from typing import Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult


class ToolSearchParams(BaseModel):
    query: str = Field(
        description=(
            "Search term. Prefix with 'select:' for exact name lookup "
            "(e.g. 'select:AskUserQuestion,EnterWorktree'), "
            "otherwise treated as keyword search across tool name/description."
        )
    )
    max_results: int = Field(default=5, ge=1, description="Max tools to return")


class ToolSearchTool(Tool):
    name = "ToolSearch"
    description = (
        "Search for additional tools not in the default list. "
        "Use 'select:ToolName' to get a specific tool by name, "
        "or pass keywords to search across tool names and descriptions."
    )
    params_model = ToolSearchParams
    category = "read"
    should_defer = False

    def __init__(self, registry: Any, protocol: str = "anthropic") -> None:
        super().__init__()
        self._registry = registry
        self._protocol = protocol

    def get_schema(self) -> dict[str, Any]:
        schema = super().get_schema()
        schema.pop("title", None)
        return schema

    async def execute(self, params: Any) -> ToolResult:
        query = params.query.strip()
        registry = self._registry
        protocol = self._protocol
        max_results = params.max_results

        if query.startswith("select:"):
            names = [n.strip() for n in query[len("select:"):].split(",") if n.strip()]
            schemas = registry.find_deferred_by_names(names, protocol)
        else:
            schemas = registry.search_deferred(query, max_results, protocol)

        if not schemas:
            available = registry.get_deferred_tool_names()
            avail_str = ", ".join(available) if available else "(none available)"
            return ToolResult(
                f'No matching deferred tools for "{query}". Available: {avail_str}'
            )

        for s in schemas:
            registry.mark_discovered(s["name"] if protocol != "openai" else s["name"])

        names = [s["name"] for s in schemas]
        return ToolResult(
            f"Found {len(schemas)} tool(s): {', '.join(names)}\n"
            + _json.dumps(schemas, indent=2)
        )
