"""Inline permission dialog widget for HITL."""

from __future__ import annotations

from mewcode.agent import PermissionResponse

_PERM_OPTIONS: list[tuple[str, PermissionResponse]] = [
    ("Yes", PermissionResponse.ALLOW),
    ("Yes, and don't ask again for this pattern", PermissionResponse.ALLOW_ALWAYS),
    ("No", PermissionResponse.DENY),
]


class InlinePermissionWidget:
    def __init__(self, tool_name: str, description: str) -> None:
        self.tool_name = tool_name
        self.description = description
        self.options = _PERM_OPTIONS

    def render(self) -> str:
        lines = [f"Permission required: {self.tool_name}"]
        if self.description:
            lines.append(f"  {self.description}")
        for i, (label, _) in enumerate(self.options, 1):
            lines.append(f"  [{i}] {label}")
        return "\n".join(lines)

    def handle_choice(self, index: int) -> PermissionResponse:
        if 0 <= index < len(self.options):
            return self.options[index][1]
        return PermissionResponse.DENY