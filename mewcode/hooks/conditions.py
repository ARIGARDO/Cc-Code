"""Condition DSL: leaf operators, compound conditions, parsing."""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_OPERATORS = ("==", "!=", "=~", "~=")


class ConditionParseError(Exception):
    pass


@dataclass
class Condition:
    field: str = ""
    operator: str = ""
    value: str = ""

    def evaluate(self, ctx: Any) -> bool:
        actual = ctx.get_field(self.field)
        if self.operator == "==":
            return actual == self.value
        if self.operator == "!=":
            return actual != self.value
        if self.operator == "=~":
            pattern = self.value
            if pattern.startswith("/") and pattern.endswith("/"):
                pattern = pattern[1:-1]
            try:
                return bool(re.search(pattern, actual))
            except re.error:
                return False
        if self.operator == "~=":
            return fnmatch.fnmatch(actual, self.value)
        return False


@dataclass
class ConditionGroup:
    conditions: list[Condition] = field(default_factory=list)
    logic: str = "and"

    def evaluate(self, ctx: Any) -> bool:
        if not self.conditions:
            return True
        results = [c.evaluate(ctx) for c in self.conditions]
        if self.logic == "and":
            return all(results)
        return any(results)


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _parse_single(expr: str) -> Condition:
    expr = expr.strip()
    for op in _OPERATORS:
        idx = expr.find(op)
        if idx != -1:
            field = expr[:idx].strip()
            value = expr[idx + len(op):].strip()
            return Condition(field=field, operator=op, value=_strip_quotes(value))
    return Condition(field=expr, operator="==", value="")


def parse_condition(expr: str) -> Condition | ConditionGroup | None:
    if not expr or not expr.strip():
        return None
    expr = expr.strip()
    has_and = "&&" in expr
    has_or = "||" in expr
    if has_and and has_or:
        raise ConditionParseError("Cannot mix '&&' and '||' in a single condition expression")
    if has_and:
        parts = expr.split("&&")
        conditions = [_parse_single(p) for p in parts]
        return ConditionGroup(conditions=conditions, logic="and")
    if has_or:
        parts = expr.split("||")
        conditions = [_parse_single(p) for p in parts]
        return ConditionGroup(conditions=conditions, logic="or")
    return _parse_single(expr)