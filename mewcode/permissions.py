"""Permission system for tool access control.

Provides PermissionChecker, Rule, and RuleEngine for checking whether
a tool execution is allowed, denied, or requires user confirmation (HITL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Rule:
    """A single permission rule: tool_name + glob pattern → decision."""
    tool_name: str
    pattern: str = "**"
    decision: str = "allow"  # "allow", "deny", "ask"


@dataclass
class CheckResult:
    """Result of a permission check."""
    decision: str  # "allow", "deny", "ask"
    reason: str = ""


class RuleEngine:
    """Stores and evaluates permission rules."""

    def __init__(self) -> None:
        self._local_rules: list[Rule] = []

    def append_local_rule(self, rule: Rule) -> None:
        self._local_rules.append(rule)

    def check(self, tool_name: str, file_path: Optional[str] = None) -> CheckResult:
        import fnmatch
        for rule in self._local_rules:
            if rule.tool_name == tool_name:
                pattern = rule.pattern
                if pattern == "**":
                    return CheckResult(decision=rule.decision)
                if file_path and fnmatch.fnmatch(file_path, pattern):
                    return CheckResult(decision=rule.decision)
        return CheckResult(decision="allow")


class PermissionChecker:
    """Checks tool execution permissions.

    Integrates with the RuleEngine and supports three modes:
    - DEFAULT: normal permission checks
    - PLAN: all write tools are denied
    """

    def __init__(self, mode: str = "default") -> None:
        self.mode = mode
        self.rule_engine = RuleEngine()

    def check(self, tool_name: str, file_path: Optional[str] = None) -> CheckResult:
        # Plan mode: deny write tools
        if self.mode == "plan":
            write_tools = {"WriteFile", "EditFile", "Bash"}
            if tool_name in write_tools:
                return CheckResult(decision="deny", reason="Plan mode: write tools disabled")
            return CheckResult(decision="allow")

        # Default: check rule engine
        return self.rule_engine.check(tool_name, file_path)