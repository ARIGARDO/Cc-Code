"""PermissionChecker: main entry point that layers all checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from mewcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from mewcode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from mewcode.permissions.rules import RuleEngine, extract_content
from mewcode.permissions.sandbox import PathSandbox


@dataclass
class Decision:
    effect: DecisionEffect
    reason: str


_PLAN_MODE_ALLOWED_TOOLS = frozenset({"Agent", "ToolSearch", "AskUserQuestion"})


class PermissionChecker:
    def __init__(
        self,
        detector: DangerousCommandDetector,
        sandbox: PathSandbox,
        rule_engine: RuleEngine,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.rule_engine = rule_engine
        self.mode = mode
        self.plan_file_path: str = ""

    def _is_plan_file(self, target_path: str) -> bool:
        if not target_path:
            return False
        if ".mewcode/plans/" in target_path.replace(os.sep, "/"):
            return True
        if self.plan_file_path:
            try:
                if os.path.abspath(target_path) == os.path.abspath(self.plan_file_path):
                    return True
            except Exception:
                pass
            if os.path.basename(target_path) == os.path.basename(self.plan_file_path):
                return True
        return False

    def check(self, tool: Any, arguments: dict[str, Any]) -> Decision:
        content = extract_content(tool.name, arguments)

        if self.mode == PermissionMode.PLAN:
            if tool.name in _PLAN_MODE_ALLOWED_TOOLS:
                return Decision("allow", "Plan 模式工具豁免")
            if tool.name in ("WriteFile", "EditFile") and self._is_plan_file(content):
                return Decision("allow", "Plan 模式 plan 文件写入豁免")

        if tool.category == "command":
            if is_safe_command(content):
                return Decision("allow", "Safe read-only command")

        if tool.category == "command":
            dangerous, reason = self.detector.detect(content)
            if dangerous:
                return Decision("deny", f"危险命令拦截: {reason}")

        if tool.category in ("read", "write") and content:
            allowed, reason = self.sandbox.check(content)
            if not allowed:
                return Decision("deny", f"路径沙箱拦截: {reason}")

        rule_effect = self.rule_engine.evaluate(tool.name, content)
        if rule_effect == "allow":
            return Decision("allow", "权限规则放行")
        if rule_effect == "deny":
            return Decision("deny", "权限规则拒绝")

        fallback = mode_decide(self.mode, tool.category)
        if fallback == "allow":
            return Decision("allow", f"权限模式 {self.mode.value} 放行")
        if fallback == "deny":
            return Decision("deny", f"权限模式 {self.mode.value} 拒绝")
        return Decision("ask", "需要用户确认")