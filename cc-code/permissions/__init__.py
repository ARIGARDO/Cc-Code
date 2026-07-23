"""Permission system for tool access control.

Provides PermissionChecker, Rule, and RuleEngine for checking whether
a tool execution is allowed, denied, or requires user confirmation (HITL).
"""

from __future__ import annotations

from mewcode.permissions.checker import Decision, PermissionChecker
from mewcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from mewcode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from mewcode.permissions.rules import Rule, RuleEngine, extract_content, parse_rule
from mewcode.permissions.sandbox import PathSandbox

__all__ = [
    "Decision",
    "DecisionEffect",
    "DangerousCommandDetector",
    "PathSandbox",
    "PermissionChecker",
    "PermissionMode",
    "Rule",
    "RuleEngine",
    "extract_content",
    "is_safe_command",
    "mode_decide",
    "parse_rule",
]