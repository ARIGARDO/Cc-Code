"""Skill command registration: register_skill_commands converts Skill catalog into PROMPT commands."""

from __future__ import annotations

import logging
from typing import Any

from mewcode.commands.registry import Command, CommandContext, CommandType, CommandRegistry

logger = logging.getLogger(__name__)


def register_skill_commands(
    registry: CommandRegistry,
    skill_loader: Any,
    skill_executor: Any,
) -> int:
    catalog = getattr(skill_loader, "catalog", None)
    if catalog is None:
        return 0

    count = 0
    for name, info in catalog.items():
        if isinstance(info, dict):
            description = info.get("description", "")
            prompt_template = info.get("prompt", "")
        else:
            description = str(info)
            prompt_template = str(info)

        handler = _make_skill_handler(name, prompt_template, skill_executor)
        cmd = Command(
            name=name,
            description=description or f"Skill: {name}",
            type=CommandType.PROMPT,
            handler=handler,
            hidden=True,
        )
        try:
            registry.register_sync(cmd)
            count += 1
        except ValueError as e:
            logger.debug("Skipping skill command %s: %s", name, e)

    return count


def _make_skill_handler(name: str, prompt_template: str, executor: Any) -> Any:
    async def handle(ctx: CommandContext) -> None:
        text = prompt_template
        if ctx.args.strip():
            text = f"{prompt_template}\n\n{ctx.args.strip()}"
        ctx.ui.send_user_message(text)

    return handle