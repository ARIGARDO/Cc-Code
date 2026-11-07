"""Adapt MCP tools to CcCode's :class:`Tool` ABC."""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

from cccode.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  JSON Schema → pydantic model (T6)
# ──────────────────────────────────────────────

def _json_type_to_python(json_type: Any) -> Any:
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    if isinstance(json_type, list):
        types = [_json_type_to_python(t) if t != "null" else type(None) for t in json_type]
        if not types:
            return Any
        from functools import reduce
        from operator import or_
        return reduce(or_, types)
    return mapping.get(json_type, Any)


def _build_params_model(
    tool_name: str, input_schema: dict[str, Any]
) -> type[BaseModel]:
    """Dynamically build a pydantic ``BaseModel`` from an MCP ``inputSchema``."""
    properties: dict[str, Any] = input_schema.get("properties", {}) or {}
    required: set[str] = set(input_schema.get("required", []) or [])

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "string") if isinstance(prop_schema, dict) else "string"
        py_type = _json_type_to_python(prop_type)
        description = prop_schema.get("description", "") if isinstance(prop_schema, dict) else ""

        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=description))
        else:
            fields[prop_name] = (Optional[py_type], Field(None, description=description))

    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in tool_name)
    extra = "allow" if input_schema.get("additionalProperties", True) is not False else "forbid"
    model = create_model(f"{safe_name}Params", __config__=ConfigDict(extra=extra), **fields)  # type: ignore[arg-type]
    return model


# ──────────────────────────────────────────────
#  Content extraction (T6)
# ──────────────────────────────────────────────

def _extract_text(content: list[Any]) -> str:
    """Flatten MCP content blocks into a single string."""
    parts: list[str] = []
    for block in content:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            parts.append(getattr(block, "text", ""))
        elif block_type == "image":
            mime = getattr(block, "mimeType", "image/png")
            parts.append(f"[image: {mime}]")
        elif block_type == "resource":
            resource = getattr(block, "resource", None)
            if resource is not None:
                text = getattr(resource, "text", None)
                if text is not None:
                    parts.append(text)
                else:
                    uri = getattr(resource, "uri", "")
                    parts.append(f"[resource: {uri}]")
        else:
            parts.append(str(block))

    if not parts:
        return "(no output)"
    return "\n".join(p for p in parts if p != "")


# ──────────────────────────────────────────────
#  MCPToolWrapper (T5)
# ──────────────────────────────────────────────

class MCPToolWrapper(Tool):
    """Adapt a single MCP tool to CcCode's :class:`Tool` interface."""

    def __init__(
        self,
        server_name: str,
        tool_def: Any,
        client: Any,
    ) -> None:
        self._server_name = server_name
        self._tool_def = tool_def
        self._client = client

        self.name = f"mcp_{server_name}_{tool_def.name}"
        self.description = getattr(tool_def, "description", "") or f"MCP tool {tool_def.name}"
        self.category = "command"
        self.should_defer = True
        self.params_model = _build_params_model(
            tool_def.name, getattr(tool_def, "inputSchema", {}) or {}
        )

    def get_schema(self) -> dict[str, Any]:
        """Return the MCP ``inputSchema``, cleaned for LLM consumption."""
        schema = getattr(self._tool_def, "inputSchema", None)
        if not schema or not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        return schema

    async def execute(self, params: Any) -> ToolResult:
        """Call the MCP tool, with lazy reconnect on dead session."""
        try:
            if not self._client.is_alive:
                await self._client.connect()

            if isinstance(params, BaseModel):
                arguments = params.model_dump(exclude_unset=True)
            elif isinstance(params, dict):
                arguments = params
            else:
                arguments = {}

            result = await self._client.call_tool(self._tool_def.name, arguments)
            output = _extract_text(result.content)
            return ToolResult(output=output, is_error=getattr(result, "isError", False))
        except Exception as e:
            logger.warning("MCP tool %s failed: %s", self.name, e)
            return ToolResult(output=f"MCP tool error: {e}", is_error=True)
