import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderConfig:
    name: str = ""
    protocol: str = "anthropic"
    base_url: Optional[str] = None
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    thinking: bool = True

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.protocol == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        elif self.protocol == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        return ""

    def get_max_output_tokens(self) -> int:
        if self.thinking:
            return 64000
        return 8192
