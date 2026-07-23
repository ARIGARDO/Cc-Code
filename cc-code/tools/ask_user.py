"""AskUserQuestion — prompt the user for structured input via the TUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult


class QuestionItem(BaseModel):
    question: str = Field(description="The complete question to ask the user")
    header: str = Field(default="", max_length=12, description="Short label/chip")
    options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of {label, description} dicts (2-4 options)",
    )
    multi_select: bool = Field(default=False)


class AskUserParams(BaseModel):
    questions: list[QuestionItem] = Field(description="Questions to ask (1-4)")


@dataclass
class AskUserEvent:
    questions: list[QuestionItem]
    future: asyncio.Future


class AskUserTool(Tool):
    name = "AskUserQuestion"
    description = (
        "Ask the user one or more questions when you need clarification. "
        "Each question can have 2-4 options. The user's answers are returned."
    )
    params_model = AskUserParams
    category = "read"
    is_system_tool = True
    should_defer = True

    def __init__(self) -> None:
        super().__init__()
        self._pending_event: Optional[AskUserEvent] = None

    @property
    def pending_event(self) -> Optional[AskUserEvent]:
        return self._pending_event

    async def execute(self, params: Any) -> ToolResult:
        future: asyncio.Future[dict[str, str]] = asyncio.Future()
        questions = list(params.questions)
        self._pending_event = AskUserEvent(questions=questions, future=future)

        try:
            answers = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            self._pending_event = None
            return ToolResult("User did not respond within 5 minutes.")
        finally:
            self._pending_event = None

        lines = [f"{q.header or 'Q' + str(i+1)}: {answers.get(str(i), '')}"
                  for i, q in enumerate(questions)]
        return ToolResult("\n".join(lines))
