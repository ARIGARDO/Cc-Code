"""Tool registry — central bookkeeping for all tools."""

from __future__ import annotations

from typing import Any, Optional

from mewcode.tools.base import Tool


class ToolRegistry:
    """Holds every registered tool and governs schema export.

    Write-once during assembly, read-only during the agent loop.
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[Tool, bool, bool]] = {}
        # name → (tool_instance, enabled, discovered)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = (tool, True, not tool.should_defer)

    def get(self, name: str) -> Optional[Tool]:
        entry = self._tools.get(name)
        if entry is None:
            return None
        tool, enabled, _ = entry
        return tool if enabled else None

    def is_enabled(self, name: str) -> bool:
        entry = self._tools.get(name)
        return entry[1] if entry else False

    def enable(self, name: str) -> None:
        entry = self._tools.get(name)
        if entry:
            self._tools[name] = (entry[0], True, entry[2])

    def disable(self, name: str) -> None:
        entry = self._tools.get(name)
        if entry:
            self._tools[name] = (entry[0], False, entry[2])

    def enable_all(self) -> None:
        for name, (tool, _, discovered) in self._tools.items():
            self._tools[name] = (tool, True, discovered)

    def mark_discovered(self, name: str) -> None:
        entry = self._tools.get(name)
        if entry:
            self._tools[name] = (entry[0], entry[1], True)

    def is_discovered(self, name: str) -> bool:
        entry = self._tools.get(name)
        return entry[2] if entry else False

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name, (tool, enabled, discovered) in self._tools.items()
            if tool.should_defer and not discovered and enabled
        ]

    def search_deferred(
        self, query: str, max_results: int = 10, protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored: list[tuple[int, str]] = []

        for name, (tool, enabled, discovered) in self._tools.items():
            if not tool.should_defer or not enabled or discovered:
                continue
            name_lower = name.lower()
            desc_lower = tool.description.lower()
            score = 0
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5
            for w in query_words:
                if w in name_lower:
                    score += 3
                if w in desc_lower:
                    score += 1
            if score > 0:
                scored.append((score, name))

        scored.sort(key=lambda x: (-x[0], x[1]))
        names = [n for _, n in scored[:max_results]]
        return [self._tool_schema(n, protocol) for n in names]

    def find_deferred_by_names(
        self, names: list[str], protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name in names:
            entry = self._tools.get(name.strip())
            if entry is None:
                continue
            tool, enabled, _ = entry
            if not tool.should_defer or not enabled:
                continue
            schemas.append(self._tool_schema(name, protocol))
        return schemas

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name, (tool, enabled, discovered) in self._tools.items():
            if not enabled:
                continue
            if tool.should_defer and not discovered:
                continue
            schemas.append(self._tool_schema(name, protocol))
        return schemas

    def _tool_schema(self, name: str, protocol: str) -> dict[str, Any]:
        tool, _, _ = self._tools[name]
        json_schema = tool.get_schema()

        if protocol == "openai":
            return {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": json_schema,
            }
        # Anthropic shape
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": json_schema,
        }

    def __len__(self) -> int:
        return len(self._tools)


# ──────────────────────────────────────────────
#  Factory (T12)
# ──────────────────────────────────────────────

def create_default_registry(file_cache: Any = None) -> ToolRegistry:
    """Return a ToolRegistry pre-loaded with the 6 core tools."""
    from mewcode.tools.read_file import ReadFile
    from mewcode.tools.write_file import WriteFile
    from mewcode.tools.edit_file import EditFile
    from mewcode.tools.bash import Bash
    from mewcode.tools.glob import Glob
    from mewcode.tools.grep import Grep

    registry = ToolRegistry()
    registry.register(ReadFile(file_cache=file_cache))
    registry.register(WriteFile(file_cache=file_cache))
    registry.register(EditFile(file_cache=file_cache))
    registry.register(Bash())
    registry.register(Glob())
    registry.register(Grep())
    return registry
