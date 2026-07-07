"""AgentTool — spawn a sub-agent with an optional model override.

Contains the model short-name mapping (T6 / checklist lines 612-637).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentToolConfig:
    """Configuration passed to AgentTool when registered."""
    allowed_tools: list[str] = field(default_factory=list)
    model_override: Optional[str] = None
    max_turns: int = 10


# ──────────────────────────────────────────────
#  Model short-name mapping (F12 / T6)
# ──────────────────────────────────────────────

MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6-20250514",
    "opus": "claude-opus-4-6-20250514",
}


def _create_client_for_model(
    model_alias: str,
    parent_config: Any,
) -> Any:
    """Build a child LLMClient for *model_alias* inheriting parent config.

    Returns an LLMClient instance using the resolved model ID.
    """
    from mewcode.config import ProviderConfig as PC
    from mewcode.client import create_client

    resolved_model = MODEL_MAP.get(model_alias, model_alias)
    child_config = PC(
        name=parent_config.name,
        protocol=parent_config.protocol,
        base_url=parent_config.base_url,
        api_key=parent_config.api_key,
        model=resolved_model,
        thinking=parent_config.thinking,
    )
    return create_client(child_config)


class AgentTool:
    """Sub-agent launcher tool — ch13 will flesh this out.

    For ch02 we only need the model-mapping entry point wired.
    """

    def __init__(
        self,
        config: AgentToolConfig,
        provider_config: Any,
        parent_agent: Any = None,
    ) -> None:
        self._config = config
        self._provider_config = provider_config
        self._parent_agent = parent_agent

    def _select_llm(self) -> Any:
        if self._config.model_override:
            return _create_client_for_model(
                self._config.model_override, self._provider_config
            )
        from mewcode.client import create_client
        return create_client(self._provider_config)

    def _inject_replacement_state(self, sub_agent: Any) -> None:
        if self._parent_agent is None:
            return
        p = self._config
        if getattr(p, "subagent_type", None) is None:
            from mewcode.context import clone_replacement_state
            sub_agent.replacement_state = clone_replacement_state(
                self._parent_agent.replacement_state
            )