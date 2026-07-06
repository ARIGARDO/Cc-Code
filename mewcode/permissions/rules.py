"""Layer 3: Rule engine with user/project/local tier YAML files."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Effect = Literal["allow", "deny"]

_RULE_RE = re.compile(r"^(\w+)\((.+)\)$")

_CONTENT_FIELDS: dict[str, str] = {
    "Bash": "command",
    "ReadFile": "file_path",
    "WriteFile": "file_path",
    "EditFile": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


@dataclass(frozen=True)
class Rule:
    tool_name: str
    pattern: str
    effect: Effect

    def matches(self, tool_name: str, content: str) -> bool:
        if self.tool_name != tool_name:
            return False
        return fnmatch.fnmatch(content, self.pattern)


def parse_rule(raw: str, effect: Effect) -> Rule:
    m = _RULE_RE.match(raw)
    if not m:
        raise ValueError(f"Invalid rule syntax: {raw!r}")
    tool_name = m.group(1)
    pattern = m.group(2)
    return Rule(tool_name=tool_name, pattern=pattern, effect=effect)


def extract_content(tool_name: str, arguments: dict[str, Any]) -> str:
    field = _CONTENT_FIELDS.get(tool_name)
    if field is None:
        return ""
    return str(arguments.get(field, ""))


def _load_rules_file(path: Path) -> list[Rule]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, list):
        return []
    rules: list[Rule] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = item.get("rule")
        effect = item.get("effect")
        if not isinstance(raw, str) or effect not in ("allow", "deny"):
            continue
        try:
            rules.append(parse_rule(raw, effect))
        except ValueError:
            continue
    return rules


class RuleEngine:
    def __init__(
        self,
        user_rules_path: str | Path | None = None,
        project_rules_path: str | Path | None = None,
        local_rules_path: str | Path | None = None,
    ) -> None:
        self._user_path = Path(user_rules_path) if user_rules_path else None
        self._project_path = Path(project_rules_path) if project_rules_path else None
        self._local_path = Path(local_rules_path) if local_rules_path else None
        self._user_rules: list[Rule] = []
        self._project_rules: list[Rule] = []
        self._local_rules: list[Rule] = []
        self._load_tiers()

    def _load_tiers(self) -> None:
        if self._user_path:
            self._user_rules = _load_rules_file(self._user_path)
        if self._project_path:
            self._project_rules = _load_rules_file(self._project_path)
        if self._local_path:
            self._local_rules = _load_rules_file(self._local_path)

    def evaluate(self, tool_name: str, content: str) -> Effect | None:
        for rules in (self._user_rules, self._project_rules, self._local_rules):
            for rule in reversed(rules):
                if rule.matches(tool_name, content):
                    return rule.effect
        return None

    def append_local_rule(self, rule: Rule) -> None:
        if self._local_path is None:
            return
        self._local_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, str]] = []
        if self._local_path.exists():
            try:
                text = self._local_path.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
                if isinstance(data, list):
                    existing = data
            except (yaml.YAMLError, OSError):
                existing = []
        existing.append({"rule": f"{rule.tool_name}({rule.pattern})", "effect": rule.effect})
        self._local_path.write_text(
            yaml.dump(existing, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        self._local_rules = _load_rules_file(self._local_path)