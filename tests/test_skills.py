"""Tests for the Skill system: parser, loader, executor, directory, LoadSkill, Agent integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mewcode.skills.parser import (
    SkillParseError,
    parse_frontmatter,
    parse_skill_file,
    substitute_arguments,
    _validate_meta,
)
from mewcode.skills.executor import (
    SkillDependencyError,
    filter_tool_registry,
)
from mewcode.skills.directory import (
    parse_tool_json,
    register_skill_tools,
    _DynamicParams,
)


# ── Helpers ──────────────────────────────────

VALID_SKILL_MD = """\
---
name: test-skill
description: A test skill
mode: inline
allowedTools:
  - Bash
  - ReadFile
---

# Test Skill Body

Do something useful with $ARGUMENTS.
"""

FORK_SKILL_MD = """\
---
name: review
description: Code review
mode: fork
context: none
allowedTools:
  - Bash
  - ReadFile
  - Grep
  - Glob
---

# Review the code.
"""


def _write_skill(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── TestParseFrontmatter ────────────────────

class TestParseFrontmatter:
    def test_valid(self):
        meta, body = parse_frontmatter(VALID_SKILL_MD)
        assert meta["name"] == "test-skill"
        assert meta["mode"] == "inline"
        assert "Test Skill Body" in body

    def test_missing_opening(self):
        with pytest.raises(SkillParseError, match="missing opening"):
            parse_frontmatter("no frontmatter here")

    def test_unclosed(self):
        with pytest.raises(SkillParseError, match="unclosed"):
            parse_frontmatter("---\nname: foo\n")

    def test_invalid_yaml(self):
        with pytest.raises(SkillParseError, match="invalid YAML"):
            parse_frontmatter("---\n: invalid\n---\nbody")

    def test_non_dict(self):
        with pytest.raises(SkillParseError, match="mapping"):
            parse_frontmatter("---\n- item1\n- item2\n---\nbody")

    def test_missing_name(self):
        with pytest.raises(SkillParseError, match="missing required field 'name'"):
            _validate_meta({"description": "desc"})

    def test_missing_description(self):
        with pytest.raises(SkillParseError, match="missing required field 'description'"):
            _validate_meta({"name": "foo"})

    def test_invalid_name_format(self):
        with pytest.raises(SkillParseError, match="invalid name"):
            _validate_meta({"name": "Foo", "description": "desc"})

    def test_invalid_name_starts_with_digit(self):
        with pytest.raises(SkillParseError, match="invalid name"):
            _validate_meta({"name": "1bad", "description": "desc"})

    def test_invalid_mode(self):
        with pytest.raises(SkillParseError, match="invalid mode"):
            _validate_meta({"name": "foo", "description": "desc", "mode": "bad"})

    def test_invalid_context(self):
        with pytest.raises(SkillParseError, match="invalid context"):
            _validate_meta({"name": "foo", "description": "desc", "context": "bad"})

    def test_nonexistent_file(self):
        with pytest.raises(SkillParseError, match="file not found"):
            parse_skill_file(Path("/nonexistent/skill.md"))

    def test_fork_mode_with_context(self):
        meta, body = parse_frontmatter(FORK_SKILL_MD)
        assert meta["mode"] == "fork"
        assert meta["context"] == "none"


# ── TestSubstituteArguments ─────────────────

class TestSubstituteArguments:
    def test_with_args(self):
        assert substitute_arguments("Hello $ARGUMENTS", "world") == "Hello world"

    def test_without_args(self):
        assert substitute_arguments("Hello $ARGUMENTS", "") == "Hello $ARGUMENTS"

    def test_no_placeholder(self):
        assert substitute_arguments("No placeholder", "args") == "No placeholder"

    def test_multiple_occurrences(self):
        assert substitute_arguments("$ARGUMENTS and $ARGUMENTS", "x") == "x and x"


# ── TestSkillLoader ─────────────────────────

class TestSkillLoader:
    def test_builtin_loading(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        skills = loader.load_all()
        assert "commit" in skills
        assert "review" in skills
        assert "test" in skills
        assert "backend-interview" in skills

    def test_project_overrides_builtin(self):
        from mewcode.skills.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".mewcode" / "skills"
            skill_dir.mkdir(parents=True)
            _write_skill(
                skill_dir / "commit.md",
                "---\nname: commit\ndescription: Custom commit\nmode: inline\n---\nCustom body",
            )
            loader = SkillLoader(tmpdir)
            skills = loader.load_all()
            assert skills["commit"].description == "Custom commit"

    def test_catalog(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        catalog = loader.get_catalog()
        names = [n for n, _ in catalog]
        assert "commit" in names
        assert "review" in names

    def test_get(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        skill = loader.get("commit")
        assert skill is not None
        assert skill.name == "commit"

    def test_get_unknown(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        assert loader.get("nonexistent") is None

    def test_hot_reload_success(self):
        from mewcode.skills.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".mewcode" / "skills"
            skill_dir.mkdir(parents=True)
            path = _write_skill(
                skill_dir / "hot.md",
                "---\nname: hot\ndescription: v1\nmode: inline\n---\nBody v1",
            )
            loader = SkillLoader(tmpdir)
            loader.load_all()
            assert loader.get("hot").description == "v1"
            path.write_text("---\nname: hot\ndescription: v2\nmode: inline\n---\nBody v2", encoding="utf-8")
            assert loader.get("hot").description == "v2"

    def test_hot_reload_failure_fallback(self):
        from mewcode.skills.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".mewcode" / "skills"
            skill_dir.mkdir(parents=True)
            path = _write_skill(
                skill_dir / "hotfail.md",
                "---\nname: hotfail\ndescription: v1\nmode: inline\n---\nBody v1",
            )
            loader = SkillLoader(tmpdir)
            loader.load_all()
            path.write_text("BROKEN YAML ---", encoding="utf-8")
            skill = loader.get("hotfail")
            assert skill is not None
            assert skill.description == "v1"

    def test_directory_skill(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        skill = loader.get("backend-interview")
        assert skill is not None
        assert skill.is_directory is True

    def test_source_label(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        assert loader.get_source_label("commit") == "builtin"
        assert loader.get_source_label("nonexistent") == "unknown"

    def test_failed_file_skipped(self):
        from mewcode.skills.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".mewcode" / "skills"
            skill_dir.mkdir(parents=True)
            _write_skill(skill_dir / "bad.md", "NOT VALID FRONTMATTER")
            _write_skill(
                skill_dir / "good.md",
                "---\nname: good\ndescription: Good\nmode: inline\n---\nBody",
            )
            loader = SkillLoader(tmpdir)
            skills = loader.load_all()
            assert "good" in skills
            assert "bad" not in skills

    def test_reload(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        skills = loader.reload()
        assert "commit" in skills


# ── TestFilterToolRegistry ──────────────────

class TestFilterToolRegistry:
    def _make_registry(self) -> Any:
        from mewcode.tools import ToolRegistry
        from mewcode.tools.base import Tool, ToolResult

        class FakeTool(Tool):
            name: str = ""
            async def execute(self, params: Any) -> ToolResult:
                return ToolResult(output="ok")

        reg = ToolRegistry()
        for n in ["Bash", "ReadFile", "Grep", "Glob", "WriteFile"]:
            t = FakeTool()
            t.name = n
            reg.register(t)

        class SystemTool(FakeTool):
            name: str = "LoadSkill"
            is_system_tool: bool = True

        reg.register(SystemTool())
        return reg

    def test_empty_allowed(self):
        reg = self._make_registry()
        result = filter_tool_registry(reg, [])
        assert result is reg

    def test_filter(self):
        reg = self._make_registry()
        result = filter_tool_registry(reg, ["Bash", "ReadFile"])
        assert "Bash" in result.list_tools()
        assert "ReadFile" in result.list_tools()
        assert "Grep" not in result.list_tools()

    def test_system_tools_passthrough(self):
        reg = self._make_registry()
        result = filter_tool_registry(reg, ["Bash"])
        assert "LoadSkill" in result.list_tools()

    def test_missing_tool_raises(self):
        reg = self._make_registry()
        with pytest.raises(SkillDependencyError, match="missing tools"):
            filter_tool_registry(reg, ["Bash", "NonExistent"])


# ── TestDirectory ───────────────────────────

class TestDirectory:
    def test_parse_tool_json_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tool.json"
            path.write_text(json.dumps({
                "tools": [{"name": "t1", "description": "d1"}]
            }))
            result = parse_tool_json(path)
            assert len(result) == 1
            assert result[0]["name"] == "t1"

    def test_parse_tool_json_single_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tool.json"
            path.write_text(json.dumps({"name": "t1", "description": "d1"}))
            result = parse_tool_json(path)
            assert len(result) == 1

    def test_register_skill_tools(self):
        from mewcode.tools import ToolRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir)
            (skill_dir / "tool.json").write_text(json.dumps({
                "tools": [{"name": "mytool", "description": "my tool", "parameters": {"type": "object", "properties": {}}}]
            }))
            refs = skill_dir / "references"
            refs.mkdir()
            (refs / "mytool.py").write_text(
                "async def execute(**kwargs): return 'hello'\n"
            )
            reg = ToolRegistry()
            count = register_skill_tools(skill_dir, reg)
            assert count == 1
            assert "mytool" in reg.list_tools()

    def test_no_tool_json(self):
        from mewcode.tools import ToolRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = ToolRegistry()
            count = register_skill_tools(Path(tmpdir), reg)
            assert count == 0

    def test_dynamic_tool_executable(self):
        from mewcode.tools import ToolRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir)
            (skill_dir / "tool.json").write_text(json.dumps({
                "tools": [{"name": "adder", "description": "add", "parameters": {"type": "object", "properties": {"a": {"type": "integer"}}}}]
            }))
            refs = skill_dir / "references"
            refs.mkdir()
            (refs / "adder.py").write_text(
                "def execute(a=0, **kwargs): return str(a + 1)\n"
            )
            reg = ToolRegistry()
            register_skill_tools(skill_dir, reg)
            tool = reg.get("adder")
            assert tool is not None
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                tool.execute(_DynamicParams(a=5))
            )
            assert result.output == "6"


# ── TestLoadSkill ───────────────────────────

class TestLoadSkill:
    def test_load_existing(self):
        from mewcode.tools.load_skill import LoadSkill
        from mewcode.skills.loader import SkillLoader
        tool = LoadSkill()
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        agent = MagicMock()
        tool.set_loader(loader)
        tool.set_agent(agent)
        import asyncio
        params = MagicMock()
        params.name = "commit"
        result = asyncio.get_event_loop().run_until_complete(tool.execute(params))
        assert "activated" in result.output
        assert not result.is_error

    def test_load_unknown(self):
        from mewcode.tools.load_skill import LoadSkill
        from mewcode.skills.loader import SkillLoader
        tool = LoadSkill()
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        agent = MagicMock()
        tool.set_loader(loader)
        tool.set_agent(agent)
        import asyncio
        params = MagicMock()
        params.name = "nonexistent"
        result = asyncio.get_event_loop().run_until_complete(tool.execute(params))
        assert result.is_error

    def test_not_initialized(self):
        from mewcode.tools.load_skill import LoadSkill
        tool = LoadSkill()
        import asyncio
        params = MagicMock()
        params.name = "commit"
        result = asyncio.get_event_loop().run_until_complete(tool.execute(params))
        assert result.is_error

    def test_is_system_tool_and_category(self):
        from mewcode.tools.load_skill import LoadSkill
        tool = LoadSkill()
        assert tool.is_system_tool is True
        assert tool.category == "read"


# ── TestAgentIntegration ────────────────────

class TestAgentIntegration:
    def test_build_environment_context_with_active_skills(self):
        from mewcode.prompts import build_environment_context
        result = build_environment_context(
            work_dir="/tmp",
            active_skills={"commit": "SOP body here"},
        )
        assert "## Active Skills" in result
        assert "### Skill: commit" in result
        assert "SOP body here" in result

    def test_build_environment_context_without_active_skills(self):
        from mewcode.prompts import build_environment_context
        result = build_environment_context(work_dir="/tmp")
        assert "## Active Skills" not in result

    def test_activate_skill(self):
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader("/tmp/nonexistent_workdir")
        loader.load_all()
        agent = MagicMock()
        agent.active_skills = {}
        agent.activate_skill = MagicMock(side_effect=lambda n, b: agent.active_skills.update({n: b}))
        agent.activate_skill("commit", "body")
        assert "commit" in agent.active_skills

    def test_clear_active_skills(self):
        agent = MagicMock()
        agent.active_skills = {"commit": "body"}
        agent.clear_active_skills = MagicMock(side_effect=agent.active_skills.clear)
        agent.clear_active_skills()
        assert len(agent.active_skills) == 0