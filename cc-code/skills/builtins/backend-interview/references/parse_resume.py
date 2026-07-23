"""parse_resume tool implementation for backend-interview skill."""

from __future__ import annotations

from pathlib import Path


async def execute(file_path: str = "", **kwargs: object) -> str:
    if not file_path:
        return "No resume file provided. Please specify a file path."

    path = Path(file_path).expanduser()
    if not path.is_file():
        return f"File not found: {file_path}"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    lines = text.strip().split("\n")
    sections: dict[str, list[str]] = {}
    current_section = "General"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isupper() or (stripped.endswith(":") and len(stripped) < 30):
            current_section = stripped.rstrip(":")
            continue
        sections.setdefault(current_section, []).append(stripped)

    result_parts = ["## Parsed Resume\n"]
    for section, items in sections.items():
        result_parts.append(f"### {section}")
        for item in items:
            result_parts.append(f"- {item}")
        result_parts.append("")

    return "\n".join(result_parts)