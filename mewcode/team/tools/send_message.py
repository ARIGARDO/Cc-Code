"""SendMessage tool — broadcast or unicast messages within a team."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mewcode.team.manager import TeamManager
from mewcode.team.mailbox import Mailbox, build_plan_approval, build_shutdown_request, build_shutdown_response, build_text_message
from mewcode.team.registry import AgentNameRegistry
from mewcode.team.types import MessageType, TeamNotFoundError
from mewcode.tools.base import Tool, ToolResult


class SendMessageParams(BaseModel):
    team: str = Field(..., description="Sanitised team slug.")
    to: str = Field(
        ...,
        description="Target member name, '*' for all non-lead members, or a raw agent_id.",
    )
    message_type: str = Field(
        "text",
        description="Message type: text | plan_approval | shutdown_request | shutdown_response.",
    )
    summary: str = Field(
        "",
        max_length=500,
        description="Short one-line summary shown in inbox listings.",
    )
    message: str = Field(
        "",
        max_length=4000,
        description="Main body text.",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Structured payload (approval flag, etc.).",
    )
    from_: str = Field(
        "lead",
        alias="from",
        description="Name of the sender (default 'lead' for the orchestrator).",
    )


class SendMessageTool(Tool):
    name: str = "SendMessage"
    description: str = (
        "Send a message to a teammate, or to every teammate ('*'). "
        "Each recipient reads their inbox independently via the same "
        "mailbox.  Use message_type='shutdown_request' to request a "
        "teammate stop, or 'plan_approval' to approve/reject a plan."
    )
    params_model: type = SendMessageParams
    category: str = "read"
    is_concurrency_safe: bool = True
    is_system_tool: bool = False

    def __init__(
        self,
        team_manager: TeamManager,
        registry: AgentNameRegistry | None = None,
        current_member: str = "lead",
    ) -> None:
        self._team_manager = team_manager
        self._registry = registry or AgentNameRegistry()
        self._current_member = current_member

    async def execute(self, params: Any) -> ToolResult:
        try:
            p = (
                params
                if isinstance(params, SendMessageParams)
                else SendMessageParams(**params)
            )
        except Exception as exc:
            return ToolResult(output=f"Invalid SendMessage args: {exc}", is_error=True)

        try:
            team = await self._team_manager.get(p.team)
        except TeamNotFoundError as exc:
            return ToolResult(output=f"{exc}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Failed to load team: {exc}", is_error=True)

        mailbox = Mailbox(team.mailbox_dir)

        # Resolve recipients
        if p.to == "*":
            targets = [
                m.name for m in team.members if m.name not in (p.from_, "lead")
            ]
            if not targets:
                targets = [m.name for m in team.members if m.name != p.from_]
        else:
            targets = [p.to]

        sender = p.from_ or self._current_member
        delivered: list[str] = []

        try:
            for target in targets:
                msg = self._build_message(sender, target, p)
                await mailbox.write(target, msg)
                delivered.append(target)
        except Exception as exc:
            return ToolResult(
                output=f"Failed to send message: {exc}",
                is_error=True,
            )

        return ToolResult(
            output=json.dumps({
                "delivered_to": delivered,
                "sender": sender,
                "timestamp": int(
                    __import__("time").time()
                ),
            })
        )

    def _build_message(
        self, sender: str, target: str, p: SendMessageParams
    ):
        if p.message_type == "text":
            return build_text_message(
                from_=sender,
                to=target,
                summary=p.summary or (p.message[:80] if p.message else ""),
                content=p.message,
            )
        if p.message_type == "plan_approval":
            approve = True
            if p.payload and "approve" in p.payload:
                approve = bool(p.payload["approve"])
            return build_plan_approval(
                from_=sender, to=target, approve=approve, feedback=p.message
            )
        if p.message_type == "shutdown_request":
            return build_shutdown_request(from_=sender, to=target, reason=p.message)
        if p.message_type == "shutdown_response":
            approve = True
            if p.payload and "approve" in p.payload:
                approve = bool(p.payload["approve"])
            return build_shutdown_response(
                from_=sender, to=target, approved=approve, reason=p.message
            )
        # Unknown type — treat as text
        return build_text_message(
            from_=sender,
            to=target,
            summary=p.summary or (p.message[:80] if p.message else ""),
            content=p.message,
        )