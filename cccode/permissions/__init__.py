"""Permission system for tool access control.

Provides PermissionChecker, Rule, and RuleEngine for checking whether
a tool execution is allowed, denied, or requires user confirmation (HITL).
"""

from __future__ import annotations

from cccode.permissions.checker import Decision, PermissionChecker
from cccode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from cccode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from cccode.permissions.rules import Rule, RuleEngine, extract_content, parse_rule
from cccode.permissions.sandbox import PathSandbox

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