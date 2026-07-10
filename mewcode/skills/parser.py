"""Skill parser: SkillDef dataclass, frontmatter parsing, argument substitution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]*$")
_VALID_MODES = {"inline", "fork"}
_VALID_CONTEXTS = {"full", "recent", "none"}


class SkillParseError(Exception):
    pass


@dataclass
class SkillDef:
    name: str
    description: str = ""
    prompt_body: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    mode: str = "inline"
    model: str = ""
    context: str = "full"
    source_path: Path | None = None
    is_directory: bool = False


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        raise SkillParseError("missing opening '---' delimiter")
    end = raw.find("---", 3)
    if end == -1:
        raise SkillParseError("unclosed frontmatter: missing closing '---'")
    yaml_text = raw[3:end].strip()
    body = raw[end + 3:].strip()
    try:
        meta = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise SkillParseError(f"invalid YAML: {e}") from e
    if not isinstance(meta, dict):
        raise SkillParseError("frontmatter must be a YAML mapping")
    return meta, body


def _validate_meta(meta: dict[str, Any]) -> None:
    name = meta.get("name")
    if not name:
        raise SkillParseError("missing required field 'name'")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SkillParseError(f"invalid name '{name}': must match {_NAME_RE.pattern}")
    desc = meta.get("description")
    if not desc:
        raise SkillParseError("missing required field 'description'")
    mode = meta.get("mode", "inline")
    if mode not in _VALID_MODES:
        raise SkillParseError(f"invalid mode '{mode}': must be one of {_VALID_MODES}")
    ctx = meta.get("context", "full")
    if ctx not in _VALID_CONTEXTS:
        raise SkillParseError(f"invalid context '{ctx}': must be one of {_VALID_CONTEXTS}")


def parse_skill_file(path: Path, is_directory: bool = False) -> SkillDef:
    if not path.is_file():
        raise SkillParseError(f"file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    _validate_meta(meta)
    allowed = meta.get("allowedTools", [])
    if isinstance(allowed, str):
        allowed = [allowed]
    return SkillDef(
        name=meta["name"],
        description=meta.get("description", ""),
        prompt_body=body,
        allowed_tools=allowed,
        mode=meta.get("mode", "inline"),
        model=meta.get("model", ""),
        context=meta.get("context", "full"),
        source_path=path,
        is_directory=is_directory,
    )


def substitute_arguments(prompt_body: str, args: str) -> str:
    if not args:
        return prompt_body
    return prompt_body.replace("$ARGUMENTS", args)