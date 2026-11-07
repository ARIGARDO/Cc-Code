"""Command parsing and completion utilities."""

from __future__ import annotations

from cccode.commands.registry import CommandRegistry


def parse_command(text: str) -> tuple[str, str, bool]:
    if not text or not text.strip():
        return ("", "", False)
    stripped = text.strip()
    if not stripped.startswith("/"):
        return ("", "", False)
    rest = stripped[1:].strip()
    if not rest:
        return ("", "", True)
    parts = rest.split(None, 1)
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return (name, args, True)


def complete(registry: CommandRegistry, prefix: str) -> list[str]:
    stripped = prefix.strip()
    if not stripped.startswith("/"):
        return []
    query = stripped[1:].lower()
    results: set[str] = set()
    for cmd in registry.list_commands(include_hidden=False):
        name_lower = cmd.name.lower()
        if name_lower.startswith(query):
            results.add(f"/{cmd.name}")
        for alias in cmd.aliases:
            alias_lower = alias.lower()
            if alias_lower.startswith(query):
                results.add(f"/{alias}")
    return sorted(results)