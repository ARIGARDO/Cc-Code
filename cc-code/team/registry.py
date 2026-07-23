"""AgentNameRegistry — bidirectional name ↔ agent_id mapping."""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """Bidirectional mapping of agent names to agent IDs.

    Designed to be shared across a single mewcode process; sub-processes
    (tmux / iterm2 backends) each hold their own independent copy that is
    not synchronised — those peers rely purely on the agent_id baked into
    messages and worktree paths.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, str] = {}
        self._by_id: dict[str, str] = {}

    def register(self, name: str, agent_id: str) -> None:
        """Register *name* ↔ *agent_id*.

        If *name* was already registered, the old mapping is replaced.
        If *agent_id* was already registered under a different name, the
        previous name is unregistered first.
        """

        with self._lock:
            # If this agent_id was known under another name, unregister it
            previous_name = self._by_id.get(agent_id)
            if previous_name and previous_name != name:
                del self._by_name[previous_name]

            # If this name pointed to a different agent_id, clean that up
            previous_id = self._by_name.get(name)
            if previous_id and previous_id != agent_id:
                if self._by_id.get(previous_id) == name:
                    del self._by_id[previous_id]

            self._by_name[name] = agent_id
            self._by_id[agent_id] = name

    def unregister(self, name: str) -> None:
        with self._lock:
            agent_id = self._by_name.pop(name, None)
            if agent_id and self._by_id.get(agent_id) == name:
                del self._by_id[agent_id]

    def unregister_by_id(self, agent_id: str) -> None:
        with self._lock:
            name = self._by_id.pop(agent_id, None)
            if name and self._by_name.get(name) == agent_id:
                del self._by_name[name]

    def resolve(self, name_or_id: str) -> str | None:
        """Return the agent_id for *name_or_id*.

        If *name_or_id* is already a registered agent_id, return it as-is.
        """
        with self._lock:
            if name_or_id in self._by_id:
                return name_or_id
            return self._by_name.get(name_or_id)

    def name_of(self, agent_id: str) -> str | None:
        with self._lock:
            return self._by_id.get(agent_id)

    def all_names(self) -> list[str]:
        with self._lock:
            return sorted(self._by_name.keys())

    def all_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._by_id.keys())

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._by_name)