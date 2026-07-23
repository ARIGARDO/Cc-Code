"""Fork mode: build forked conversation with context isolation."""

from __future__ import annotations

import copy
import logging

from mewcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
)

logger = logging.getLogger(__name__)

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = f"""{FORK_BOILERPLATE_TAG}
You are a forked sub-agent with an isolated context. You have access to the same tools as the parent agent but operate independently. Complete the task given to you without modifying the parent conversation.
{FORK_BOILERPLATE_TAG}"""


class ForkError(Exception):
    pass


def build_forked_messages(
    conversation: ConversationManager,
    task: str,
) -> ConversationManager:
    """Build a forked conversation for a sub-agent.

    1. Check for nested fork (scan for FORK_BOILERPLATE_TAG).
    2. Deep-copy parent conversation history.
    3. Patch pending tool_uses with "interrupted" placeholder.
    4. Append fork boilerplate + task as user message.
    """
    for msg in conversation.history:
        if msg.content and FORK_BOILERPLATE_TAG in msg.content:
            raise ForkError("Cannot fork from a forked agent.")

    forked = ConversationManager()
    forked.history = copy.deepcopy(conversation.history)
    forked.env_injected = conversation.env_injected
    forked.ltm_injected = conversation.ltm_injected

    if forked.history and forked.history[-1].role == "assistant":
        last = forked.history[-1]
        pending_ids: list[str] = []
        if last.tool_uses:
            existing_result_ids = set()
            for msg in forked.history:
                for tr in msg.tool_results:
                    existing_result_ids.add(tr.tool_use_id)
            for tu in last.tool_uses:
                if tu.id not in existing_result_ids:
                    pending_ids.append(tu.id)

        if pending_ids:
            placeholders = [
                ToolResultBlock(
                    tool_use_id=tid,
                    content="interrupted",
                    is_error=True,
                )
                for tid in pending_ids
            ]
            forked.history.append(
                Message(role="user", tool_results=placeholders)
            )

    forked.add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")

    return forked