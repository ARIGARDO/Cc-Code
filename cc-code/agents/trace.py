"""TraceManager: call-tree tracking for sub-agent spawns."""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TraceNode:
    agent_id: str = ""
    agent_type: str = ""
    parent_id: str = ""
    trace_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = "running"
    start_time: str = ""
    end_time: str = ""


class TraceManager:
    """Track parent/child/trace relationships for sub-agent spawns."""

    def __init__(self) -> None:
        self._nodes: dict[str, TraceNode] = {}

    def create(
        self,
        agent_type: str,
        parent_id: str = "",
        trace_id: str = "",
    ) -> TraceNode:
        """Create a new trace node and return it."""
        agent_id = uuid.uuid4().hex[:12]
        if not trace_id:
            trace_id = uuid.uuid4().hex[:12]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        node = TraceNode(
            agent_id=agent_id,
            agent_type=agent_type,
            parent_id=parent_id,
            trace_id=trace_id,
            start_time=now,
        )
        self._nodes[agent_id] = node
        return node

    def update(self, agent_id: str, **kwargs: Any) -> None:
        """Update fields on an existing trace node."""
        node = self._nodes.get(agent_id)
        if node is None:
            return
        for key, val in kwargs.items():
            if hasattr(node, key):
                setattr(node, key, val)

    def complete(self, agent_id: str, status: str = "completed") -> None:
        """Mark a trace node as complete with end time and status."""
        node = self._nodes.get(agent_id)
        if node is None:
            return
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        node.end_time = now
        node.status = status

    def get_tree(self, trace_id: str) -> list[TraceNode]:
        """Return all nodes belonging to a trace."""
        return [n for n in self._nodes.values() if n.trace_id == trace_id]

    def get_total_tokens(self, trace_id: str) -> tuple[int, int]:
        """Return (total_input_tokens, total_output_tokens) for a trace."""
        nodes = self.get_tree(trace_id)
        total_in = sum(n.input_tokens for n in nodes)
        total_out = sum(n.output_tokens for n in nodes)
        return total_in, total_out