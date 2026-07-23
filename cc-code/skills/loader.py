"""Skill loader: three-tier search (project > user > builtin) with hot reload."""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from mewcode.skills.parser import SkillDef, SkillParseError, parse_skill_file

logger = logging.getLogger(__name__)

PROJECT_SKILLS_DIR = ".mewcode/skills"
USER_SKILLS_DIR = "~/.mewcode/skills"


class SkillLoader:
    def __init__(self, work_dir: str | Path) -> None:
        self._work_dir = Path(work_dir).resolve()
        self._project_dir = self._work_dir / PROJECT_SKILLS_DIR
        self._user_dir = Path(USER_SKILLS_DIR).expanduser()
        self._skills: dict[str, SkillDef] = {}
        self._cache: dict[str, SkillDef] = {}

    def load_all(self) -> dict[str, SkillDef]:
        self._skills.clear()
        self._cache.clear()
        self._scan_directory(self._project_dir, "project")
        self._scan_directory(self._user_dir, "user")
        self._load_builtins()
        return dict(self._skills)

    def _scan_directory(self, path: Path, source: str) -> None:
        if not path.is_dir():
            return
        for entry in sorted(path.iterdir()):
            try:
                if entry.is_dir():
                    skill_md = entry / "SKILL.md"
                    if skill_md.is_file():
                        self._try_load(skill_md, is_directory=True, source=source)
                elif entry.suffix == ".md":
                    self._try_load(entry, is_directory=False, source=source)
            except Exception as e:
                logger.warning("Skipping %s skill '%s': %s", source, entry.name, e)

    def _try_load(self, path: Path, is_directory: bool, source: str) -> None:
        try:
            skill = parse_skill_file(path, is_directory=is_directory)
        except SkillParseError as e:
            logger.warning("Skipping %s skill '%s': %s", source, path.name, e)
            return
        if skill.name not in self._skills:
            self._skills[skill.name] = skill
            self._cache[skill.name] = skill

    def _load_builtins(self) -> None:
        try:
            builtin_root = importlib.resources.files("mewcode.skills.builtins")
        except (ModuleNotFoundError, TypeError):
            return
        try:
            items = builtin_root.iterdir()
        except (AttributeError, TypeError):
            return
        for item in items:
            try:
                name = item.name
                if name.startswith("_"):
                    continue
                try:
                    is_dir = item.is_dir()
                except (AttributeError, TypeError):
                    continue
                if is_dir:
                    skill_md_path = item.joinpath("SKILL.md")
                    try:
                        skill_md_path.read_text(encoding="utf-8")
                    except (AttributeError, TypeError, FileNotFoundError):
                        continue
                    real_path = Path(str(skill_md_path))
                    self._try_load(real_path, is_directory=True, source="builtin")
            except Exception as e:
                logger.warning("Skipping builtin skill: %s", e)

    def get(self, name: str) -> SkillDef | None:
        cached = self._skills.get(name)
        if cached is None:
            return None
        if cached.source_path and cached.source_path.is_file():
            try:
                fresh = parse_skill_file(cached.source_path, is_directory=cached.is_directory)
                self._skills[name] = fresh
                self._cache[name] = fresh
                return fresh
            except SkillParseError as e:
                logger.warning("Hot reload failed for '%s': %s; using cache", name, e)
                return self._cache.get(name)
        return cached

    def get_catalog(self) -> list[tuple[str, str]]:
        return [(s.name, s.description) for s in self._skills.values()]

    def get_source_label(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None or skill.source_path is None:
            return "unknown"
        path_str = str(skill.source_path)
        if self._project_dir.exists() and path_str.startswith(str(self._project_dir)):
            return "project"
        if self._user_dir.exists() and path_str.startswith(str(self._user_dir)):
            return "user"
        return "builtin"

    def reload(self) -> dict[str, SkillDef]:
        return self.load_all()