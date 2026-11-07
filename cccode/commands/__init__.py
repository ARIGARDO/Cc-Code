"""Command system for CcCode."""

from cccode.commands.registry import Command, CommandContext, CommandRegistry, CommandType
from cccode.commands.parser import parse_command, complete
from cccode.commands.handlers import register_all_commands, ALL_COMMANDS

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