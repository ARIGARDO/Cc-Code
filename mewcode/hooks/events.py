"""Lifecycle events for the hook system."""

from __future__ import annotations

from enum import StrEnum


class LifecycleEvent(StrEnum):
    session_start = "session_start"
    session_end = "session_end"
    turn_start = "turn_start"
    turn_end = "turn_end"
    pre_tool_use = "pre_tool_use"
    post_tool_use = "post_tool_use"
    pre_send = "pre_send"
    post_receive = "post_receive"
    startup = "startup"
    shutdown = "shutdown"
    error = "error"
    compact = "compact"
    permission_request = "permission_request"
    file_change = "file_change"
    command_execute = "command_execute"