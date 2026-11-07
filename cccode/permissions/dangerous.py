"""Layer 1: Dangerous command detection and safe command whitelist."""

from __future__ import annotations

import re


_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-rf)\s+/(?!\S)"), "递归强制删除根目录"),
    (re.compile(r"\bmkfs\."), "磁盘格式化"),
    (re.compile(r"\bdd\s+.*of=/dev/"), "直接写入设备"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/"), "递归修改根目录权限为777"),
    (re.compile(r":\(\)\{\s*:\|:&\s*\};:"), "fork bomb"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh"), "远程脚本执行"),
    (re.compile(r">\s*/dev/sd"), "直接写入块设备"),
    (re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*|-fr)\s+/(?!\S)"), "递归强制删除根目录"),
]


# Only commands whose complete argument forms are known to be read-only.
_SAFE_COMMANDS = frozenset({
    "ls", "pwd", "whoami", "id", "uname", "hostname", "date", "uptime",
    "python --version", "python3 --version", "node --version", "node -v",
    "npm -v", "ruff --version", "pytest --version",
})


class DangerousCommandDetector:
    def __init__(self, extra_patterns: list[tuple[re.Pattern[str], str]] | None = None) -> None:
        self._patterns = list(_DANGEROUS_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def detect(self, command: str) -> tuple[bool, str]:
        for pattern, reason in self._patterns:
            if pattern.search(command):
                return (True, reason)
        return (False, "")


def is_safe_command(command: str) -> bool:
    """Recognize a deliberately small set of commands, never shell syntax."""
    import shlex

    if any(char in command for char in "\n\r;|&<>$`\\*?[]{}()"):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    if " ".join(parts) in _SAFE_COMMANDS:
        return True
    # ls accepts paths and flags, but not shell expansion or additional commands.
    return parts[0] == "ls" and all(not part.startswith("--") for part in parts[1:])
