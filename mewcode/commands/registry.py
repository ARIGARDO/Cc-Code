"""Core command registry types: CommandType, UIController, CommandContext, Command, CommandRegistry."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)


class CommandType(str, Enum):
    LOCAL = "local"
    LOCAL_UI = "local_ui"
    PROMPT = "prompt"


class UIController(Protocol):
    def add_system_message(self, message: str) -> None:
        ...

    def send_user_message(self, text: str) -> None:
        ...

    def set_plan_mode(self, enabled: bool) -> None:
        ...

    def get_token_count(self) -> tuple[int, int]:
        ...

    def refresh_status(self) -> None:
        ...


@dataclass
class CommandContext:
    args: str = ""
    agent: Any = None
    conversation: Any = None
    session: Any = None
    session_manager: Any = None
    memory_manager: Any = None
    ui: UIController = field(default=None, repr=False)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Command:
    name: str
    description: str = ""
    type: CommandType = CommandType.LOCAL
    handler: Callable[[CommandContext], Any] | None = None
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    arg_prompt: str = ""
    hidden: bool = False


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, cmd: Command) -> None:
        async with self._lock:
            self._register_sync(cmd)

    def register_sync(self, cmd: Command) -> None:
        self._register_sync(cmd)

    def _register_sync(self, cmd: Command) -> None:
        name_lower = cmd.name.lower()
        if name_lower in self._commands:
            raise ValueError(f"command '{cmd.name}' conflicts with existing command")
        for alias in cmd.aliases:
            alias_lower = alias.lower()
            existing = self._alias_map.get(alias_lower)
            if existing is not None and existing != name_lower:
                raise ValueError(f"alias '{alias}' for '{cmd.name}' conflicts with '{existing}'")
            if alias_lower in self._commands:
                raise ValueError(f"alias '{alias}' for '{cmd.name}' conflicts with existing command name")
        self._commands[name_lower] = cmd
        for alias in cmd.aliases:
            self._alias_map[alias.lower()] = name_lower

    def find(self, name: str) -> Optional[Command]:
        name_lower = name.lower()
        cmd = self._commands.get(name_lower)
        if cmd is not None:
            return cmd
        canonical = self._alias_map.get(name_lower)
        if canonical is not None:
            return self._commands.get(canonical)
        return None

    def list_commands(self, include_hidden: bool = False) -> list[Command]:
        result = []
        for cmd in self._commands.values():
            if include_hidden or not cmd.hidden:
                result.append(cmd)
        return sorted(result, key=lambda c: c.name)

    async def unregister(self, name: str) -> bool:
        async with self._lock:
            name_lower = name.lower()
            cmd = self._commands.pop(name_lower, None)
            if cmd is None:
                return False
            to_remove = [k for k, v in self._alias_map.items() if v == name_lower]
            for key in to_remove:
                del self._alias_map[key]
            return True