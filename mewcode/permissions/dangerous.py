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


_SAFE_COMMANDS: frozenset[str] = frozenset({
    "ls",
    "ll",
    "pwd",
    "whoami",
    "id",
    "uname",
    "hostname",
    "date",
    "uptime",
    "df",
    "du",
    "free",
    "top",
    "ps",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "file",
    "stat",
    "which",
    "whereis",
    "find",
    "locate",
    "echo",
    "printf",
    "tee",
    "sort",
    "uniq",
    "diff",
    "comm",
    "cut",
    "paste",
    "tr",
    "fold",
    "fmt",
    "column",
    "expand",
    "unexpand",
    "od",
    "hexdump",
    "xxd",
    "md5sum",
    "sha1sum",
    "sha256sum",
    "sha512sum",
    "base64",
    "basename",
    "dirname",
    "realpath",
    "readlink",
    "tree",
    "type",
    "command",
    "env",
    "printenv",
    "set",
    "export",
    "alias",
    "unalias",
    "history",
    "git status",
    "git diff",
    "git log",
    "git show",
    "git branch",
    "git tag",
    "git remote",
    "git stash list",
    "git config",
    "git rev-parse",
    "git ls-files",
    "git ls-tree",
    "git describe",
    "git shortlog",
    "git reflog",
    "git blame",
    "git whatchanged",
    "git var",
    "go version",
    "go env",
    "go list",
    "go vet",
    "go doc",
    "python --version",
    "python3 --version",
    "python -c",
    "python3 -c",
    "pip list",
    "pip show",
    "pip freeze",
    "npm -v",
    "node -v",
    "npx -v",
    "yarn -v",
    "pnpm -v",
    "rustc --version",
    "cargo --version",
    "java -version",
    "javac -version",
    "mvn -version",
    "gradle -version",
    "ruby --version",
    "gem --version",
    "bundle --version",
    "php --version",
    "composer --version",
    "dotnet --version",
    "docker version",
    "docker info",
    "docker images",
    "docker ps",
    "make -n",
    "cmake --version",
    "gcc --version",
    "g++ --version",
    "clang --version",
    "rustfmt --version",
    "cargo fmt --check",
    "ruff --version",
    "mypy --version",
    "pytest --version",
    "black --version",
    "isort --version",
    "pre-commit --version",
})

_SHELL_METACHARACTERS = frozenset({"|", ";", "&&", ">", "$(", "`"})


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
    stripped = command.strip()
    if not stripped:
        return False
    for meta in _SHELL_METACHARACTERS:
        if meta in stripped:
            return False
    if stripped in _SAFE_COMMANDS:
        return True
    for safe in _SAFE_COMMANDS:
        if stripped.startswith(safe + " "):
            return True
    return False