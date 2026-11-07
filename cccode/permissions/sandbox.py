"""Layer 2: Path sandbox for file access control."""

from __future__ import annotations

import tempfile
from pathlib import Path


class PathSandbox:
    def __init__(self, project_root: str | Path, extra_allowed: list[str | Path] | None = None) -> None:
        self._project_root = Path(project_root).resolve()
        self._allowed_roots: list[Path] = [
            self._project_root,
            Path(tempfile.gettempdir()).resolve(),
        ]
        if extra_allowed:
            for p in extra_allowed:
                self._allowed_roots.append(Path(p).resolve())

    @property
    def project_root(self) -> Path:
        return self._project_root

    def check(self, path: str | Path) -> tuple[bool, str]:
        target = Path(path)
        expanded = target.expanduser()
        if not expanded.is_absolute():
            expanded = self._project_root / expanded
        try:
            resolved = expanded.resolve(strict=False)
        except Exception:
            return (False, f"路径 {path} 超出沙箱范围")
        for root in self._allowed_roots:
            try:
                resolved.relative_to(root)
                return (True, "")
            except ValueError:
                continue
        return (False, f"路径 {path} 超出沙箱范围")
