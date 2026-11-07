"""PermissionChecker: main entry point that layers all checks."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Any

from cccode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from cccode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from cccode.permissions.rules import RuleEngine, extract_content
from cccode.permissions.sandbox import PathSandbox


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
        if self.plan_file_path:
            try:
                root = self.sandbox.project_root
                target = Path(target_path).expanduser()
                plan = Path(self.plan_file_path).expanduser()
                return (root / target).resolve() == (root / plan).resolve()
            except (OSError, RuntimeError):
                return False
        return False

    def check(self, tool: Any, arguments: dict[str, Any]) -> Decision:
        content = extract_content(tool.name, arguments)

        if tool.category == "command":
            dangerous, reason = self.detector.detect(content)
            if dangerous:
                return Decision("deny", f"危险命令拦截: {reason}")

        path = arguments.get("path", ".") if tool.name in ("Glob", "Grep") else content
        if tool.name in ("ReadFile", "WriteFile", "EditFile", "Glob", "Grep") and path:
            allowed, reason = self.sandbox.check(path)
            if not allowed:
                return Decision("deny", f"路径沙箱拦截: {reason}")

        rule_effect = self.rule_engine.evaluate(tool.name, content)
        if rule_effect == "deny":
            return Decision("deny", "权限规则拒绝")

        if self.mode == PermissionMode.PLAN:
            if tool.name in _PLAN_MODE_ALLOWED_TOOLS:
                return Decision("allow", "Plan 模式工具豁免")
            if tool.name in ("WriteFile", "EditFile") and self._is_plan_file(content):
                return Decision("allow", "Plan 模式 plan 文件写入豁免")
            if tool.category in ("write", "command") and not (tool.name == "Bash" and is_safe_command(content)):
                return Decision("deny", "Plan 模式禁止写入和执行命令")

        if rule_effect == "allow":
            return Decision("allow", "权限规则放行")
        if tool.name == "Bash" and is_safe_command(content):
            return Decision("allow", "Safe read-only command")

        fallback = mode_decide(self.mode, tool.category)
        if fallback == "allow":
            return Decision("allow", f"权限模式 {self.mode.value} 放行")
        if fallback == "deny":
            return Decision("deny", f"权限模式 {self.mode.value} 拒绝")
        return Decision("ask", "需要用户确认")
