"""Command system for CcCode."""

from mewcode.commands.registry import Command, CommandContext, CommandRegistry, CommandType
from mewcode.commands.parser import parse_command, complete
from mewcode.commands.handlers import register_all_commands, ALL_COMMANDS

__all__ = [
    "Command",
    "CommandContext",
    "CommandRegistry",
    "CommandType",
    "parse_command",
    "complete",
    "register_all_commands",
    "ALL_COMMANDS",
]