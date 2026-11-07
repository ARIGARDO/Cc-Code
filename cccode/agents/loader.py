"""Agent loader: project → user → builtin priority loading."""

from __future__ import annotations

import logging
from pathlib import Path

from cccode.agents.parser import AgentDef, AgentParseError, parse_agent_file

logger = logging.getLogger(__name__)

PROJECT_AGENTS_DIR = ".cccode/agents"
USER_AGENTS_DIR = "~/.cccode/agents"


class AgentLoader:
    """Load agent definitions from project, user, and builtin sources."""

    def __init__(
        self,
        work_dir: Path,
        enable_verification: bool = False,
    ) -> None:
        self._work_dir = work_dir
        self._enable_verification = enable_verification
        self._agents: dict[str, AgentDef] = {}

    def _scan_directory(self, directory: Path, source: str) -> list[AgentDef]:
        """Scan a directory for *.md agent definitions."""
        results: list[AgentDef] = []
        if not directory.exists():
            return results
        for path in sorted(directory.glob("*.md")):
            try:
                agent_def = parse_agent_file(path, source=source)
                results.append(agent_def)
            except AgentParseError as e:
                logger.warning("Skipping agent file %s: %s", path, e)
            except Exception as e:
                logger.warning("Error loading agent file %s: %s", path, e)
        return results

    def _load_builtins(self) -> list[AgentDef]:
        """Load builtin agent definitions from the package."""
        results: list[AgentDef] = []
        builtin_dir = Path(__file__).parent / "builtins"
        if not builtin_dir.exists():
            return results
        for path in sorted(builtin_dir.glob("*.md")):
            try:
                agent_def = parse_agent_file(path, source="builtin")
                if agent_def.agent_type == "Verification" and not self._enable_verification:
                    continue
                results.append(agent_def)
            except AgentParseError as e:
                logger.warning("Skipping builtin agent %s: %s", path, e)
            except Exception as e:
                logger.warning("Error loading builtin agent %s: %s", path, e)
        return results

    def load_all(self) -> None:
        """Load all agents: project → user → builtin (first-wins priority)."""
        self._agents.clear()

        project_dir = self._work_dir / PROJECT_AGENTS_DIR
        user_dir = Path(USER_AGENTS_DIR).expanduser()

        for agent_def in self._scan_directory(project_dir, source="project"):
            self._agents[agent_def.agent_type] = agent_def

        for agent_def in self._scan_directory(user_dir, source="user"):
            if agent_def.agent_type not in self._agents:
                self._agents[agent_def.agent_type] = agent_def

        for agent_def in self._load_builtins():
            if agent_def.agent_type not in self._agents:
                self._agents[agent_def.agent_type] = agent_def

    def get(self, agent_type: str) -> AgentDef | None:
        """Get an agent definition by type, with optional hot-reload."""
        agent_def = self._agents.get(agent_type)
        if agent_def is None:
            return None
        if agent_def.file_path and Path(agent_def.file_path).exists():
            try:
                reloaded = parse_agent_file(
                    Path(agent_def.file_path), source=agent_def.source
                )
                self._agents[agent_type] = reloaded
                return reloaded
            except AgentParseError as e:
                logger.warning("Hot-reload failed for %s: %s", agent_type, e)
                return agent_def
        return agent_def

    def list_agents(self) -> list[tuple[str, str]]:
        """Return (agent_type, when_to_use) pairs for all loaded agents."""
        return [(a.agent_type, a.when_to_use) for a in self._agents.values()]