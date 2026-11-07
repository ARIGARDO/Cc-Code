"""Skill command registration: register_skill_commands converts Skill catalog into commands."""

from __future__ import annotations

import logging
from typing import Any

from cccode.commands.registry import Command, CommandContext, CommandType, CommandRegistry

logger = logging.getLogger(__name__)

_REGISTERED_SKILL_NAMES: set[str] = set()


def register_skill_commands(
    registry: CommandRegistry,
    skill_loader: Any,
    skill_executor: Any,
) -> int:
    global _REGISTERED_SKILL_NAMES

    for name in list(_REGISTERED_SKILL_NAMES):
        try:
            registry._commands.pop(name.lower(), None)
            for k in list(registry._alias_map.keys()):
                if registry._alias_map.get(k) == name.lower():
                    del registry._alias_map[k]
        except Exception:
            pass
    _REGISTERED_SKILL_NAMES.clear()

    catalog = skill_loader.get_catalog()
    if not catalog:
        return 0

    count = 0
    for sname, sdesc in catalog:
        skill = skill_loader.get(sname)
        if skill is None:
            continue
        handler = _make_skill_handler(skill, skill_executor)
        cmd = Command(
            name=sname,
            description=f"{sdesc} [skill]",
            type=CommandType.PROMPT if skill.mode == "fork" else CommandType.LOCAL,
            handler=handler,
            hidden=True,
        )
        try:
            registry.register_sync(cmd)
            _REGISTERED_SKILL_NAMES.add(sname)
            count += 1
        except ValueError:
            existing = registry._commands.pop(sname.lower(), None)
            if existing is not None:
                for k in list(registry._alias_map.keys()):
                    if registry._alias_map.get(k) == sname.lower():
                        del registry._alias_map[k]
                logger.debug("Replacing existing command '%s' with skill command", sname)
                registry.register_sync(cmd)
                _REGISTERED_SKILL_NAMES.add(sname)
                count += 1
            else:
                logger.debug("Skipping skill command %s: conflict", sname)

    return count


def _make_skill_handler(skill: Any, executor: Any) -> Any:
    if skill.mode == "fork":

        async def handle(ctx: CommandContext) -> None:
            ctx.ui.add_system_message(f"Activating skill: {skill.name} (fork mode)...")
            try:
                result = await executor.execute_fork(skill, ctx.args)
                if result:
                    ctx.ui.add_system_message(f"[{skill.name} skill result]\n{result}")
                else:
                    ctx.ui.add_system_message(f"[{skill.name} skill completed (no output)]")
            except Exception as e:
                ctx.ui.add_system_message(f"[{skill.name} skill error] {e}")

        return handle
    else:

        async def handle(ctx: CommandContext) -> None:
            ctx.ui.add_system_message(f"Activating skill: {skill.name} (inline mode)")
            await executor.execute_inline(skill, ctx.args)
            trigger = ctx.args.strip() if ctx.args.strip() else f"Execute skill: {skill.name}"
            ctx.ui.send_user_message(trigger)

        return handle