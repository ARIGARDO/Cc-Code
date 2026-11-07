"""Project instructions: @include expansion and three-layer loading."""

from __future__ import annotations

from pathlib import Path

MAX_INCLUDE_DEPTH = 5
INCLUDE_PREFIX = "@include "


def process_includes(
    content: str,
    base_dir: Path,
    project_root: Path,
    depth: int = 0,
) -> str:
    if depth >= MAX_INCLUDE_DEPTH:
        return content

    resolved_root = project_root.resolve()
    lines = content.split("\n")
    result: list[str] = []

    for line in lines:
        if not line.strip().startswith(INCLUDE_PREFIX):
            result.append(line)
            continue

        rel_path = line.strip()[len(INCLUDE_PREFIX):].strip()
        if not rel_path:
            result.append(line)
            continue

        abs_path = (base_dir / rel_path).resolve()

        try:
            abs_path.relative_to(resolved_root)
        except ValueError:
            result.append("<!-- @include blocked: path outside project -->")
            continue

        if not abs_path.is_file():
            result.append("<!-- @include skipped: file not found -->")
            continue

        try:
            included = abs_path.read_text(encoding="utf-8")
        except OSError:
            result.append("<!-- @include skipped: file not found -->")
            continue

        expanded = process_includes(included, abs_path.parent, project_root, depth + 1)
        result.append(expanded)

    return "\n".join(result)


def load_instructions(project_root: str | Path) -> str:
    root = Path(project_root).resolve()
    home = Path.home()

    layers = [
        root / "CCCODE.md",
        root / ".cccode" / "CCCODE.md",
        home / ".cccode" / "CCCODE.md",
    ]

    segments: list[str] = []
    for path in layers:
        if path.is_file():
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            expanded = process_includes(raw, path.parent, root)
            segments.append(expanded)

    return "\n---\n".join(segments)