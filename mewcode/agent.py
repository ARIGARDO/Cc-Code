"""Agent loop: orchestrates LLM calls, tool execution, and event streaming."""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
import uuid
from collections.abc import AsyncIterator, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

from mewcode.conversation import (
    ConversationManager,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from mewcode.memory.auto_memory import should_trigger_extraction
from mewcode.context import (
    CompactCircuitBreaker,
    CompactEvent,
    ContentReplacementState,
    RecoveryState,
    append_replacement_records,
    apply_tool_result_budget,
    auto_compact,
    create_replacement_state,
    ensure_session_dir,
)
from mewcode.permissions.modes import PermissionMode
from mewcode.permissions.rules import extract_content
from mewcode.tools.base import (
    MAX_OUTPUT_CHARS,
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    ToolResult,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Constants (checklist items)
# ──────────────────────────────────────────────

MEMORY_EXTRACTION_INTERVAL = 3
MAX_TOKENS_CEILING = 64000
MAX_OUTPUT_TOKENS_RECOVERIES = 3
SINGLE_RESULT_CHAR_LIMIT = 32000

# For plan slug generation
_ADJECTIVES = [
    "bright", "calm", "clear", "crisp", "daily", "deep", "early", "fair",
    "fresh", "gentle", "happy", "quick", "sharp", "smart", "steady", "strong",
    "swift", "tender", "thick", "vital", "warm", "swift", "quiet", "neat"
]
_NOUNS = [
    "alpha", "arrow", "beacon", "blade", "bloom", "branch", "bridge", "cabin",
    "delta", "echo", "forge", "grove", "harbor", "haven", "horizon", "index",
    "knife", "lattice", "maple", "north", "orbit", "pioneer", "river", "summit"
]

# ──────────────────────────────────────────────
#  PermissionResponse enum (three states)
# ──────────────────────────────────────────────

class PermissionResponse(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"

# ──────────────────────────────────────────────
#  Agent-event types (11 dataclasses + PermissionRequest)
# ──────────────────────────────────────────────

@dataclass
class StreamText:
    text: str

@dataclass
class ThinkingText:
    text: str

@dataclass
class RetryEvent:
    reason: str

@dataclass
class ToolUseEvent:
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]

@dataclass
class ToolResultEvent:
    tool_id: str
    tool_name: str
    result: str
    is_error: bool

@dataclass
class TurnComplete:
    pass

@dataclass
class LoopComplete:
    stop_reason: str

@dataclass
class UsageEvent:
    input_tokens: int
    output_tokens: int
    total_input: int
    total_output: int

@dataclass
class ErrorEvent:
    message: str

@dataclass
class CompactNotification:
    message: str

@dataclass
class PersistNotification:
    tool_use_id: str
    original_chars: int
    preview_chars: int

@dataclass
class HookEvent:
    hook_name: str
    message: str

@dataclass
class PermissionRequest:
    tool_name: str
    tool_args: dict[str, Any]
    future: asyncio.Future[PermissionResponse]

AgentEvent = Union[
    StreamText,
    ThinkingText,
    RetryEvent,
    ToolUseEvent,
    ToolResultEvent,
    TurnComplete,
    LoopComplete,
    UsageEvent,
    ErrorEvent,
    CompactNotification,
    PersistNotification,
    HookEvent,
    PermissionRequest,
]

# ──────────────────────────────────────────────
#  ToolBatch and partition_tool_calls
# ──────────────────────────────────────────────

@dataclass
class ToolBatch:
    concurrent: bool
    calls: list[ToolUseBlock]

def partition_tool_calls(
    tool_calls: list[ToolUseBlock],
    registry: Any,
) -> list[ToolBatch]:
    """Group tool calls into batches based on concurrency safety.

    Consecutive safe tools are grouped into a concurrent batch that runs in parallel.
    Non-safe tools are each put into their own sequential batch.
    Disabled tools are skipped entirely.
    """
    batches: list[ToolBatch] = []
    current_safe: list[ToolUseBlock] = []

    for tc in tool_calls:
        tool = registry.get(tc.name)
        if tool is None or not registry.is_enabled(tc.name):
            batches.append(ToolBatch(concurrent=False, calls=[tc]))
            continue
        safe = tool.is_concurrency_safe
        if safe:
            current_safe.append(tc)
        else:
            if current_safe:
                batches.append(ToolBatch(concurrent=True, calls=current_safe))
                current_safe = []
            batches.append(ToolBatch(concurrent=False, calls=[tc]))

    if current_safe:
        batches.append(ToolBatch(concurrent=True, calls=current_safe))

    return batches

# ──────────────────────────────────────────────
#  LLMResponse and StreamCollector
# ──────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolUseBlock]
    thinking_blocks: list[ThinkingBlock]
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""

class StreamCollector:
    """Collects StreamEvents from LLM client into an LLMResponse while yielding AgentEvents."""

    def __init__(self) -> None:
        self.text = ""
        self.tool_calls: list[ToolUseBlock] = []
        self.thinking_blocks: list[ThinkingBlock] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.stop_reason = ""

    async def consume(
        self,
        stream: AsyncIterator[StreamEvent],
    ) -> AsyncGenerator[AgentEvent, None]:
        pending_tools: dict[str, tuple[str, str]] = {}

        async for event in stream:
            if isinstance(event, TextDelta):
                self.text += event.text
                yield StreamText(text=event.text)

            elif isinstance(event, ThinkingDelta):
                yield ThinkingText(text=event.text)

            elif isinstance(event, ThinkingComplete):
                self.thinking_blocks.append(
                    ThinkingBlock(thinking=event.thinking, signature=event.signature)
                )
                self.text += event.thinking

            elif isinstance(event, ToolCallStart):
                pending_tools[event.tool_id] = (event.tool_name, "")

            elif isinstance(event, ToolCallDelta):
                pass

            elif isinstance(event, ToolCallComplete):
                self.tool_calls.append(
                    ToolUseBlock(
                        id=event.tool_id,
                        name=event.tool_name,
                        arguments=event.arguments,
                    )
                )
                yield ToolUseEvent(
                    tool_id=event.tool_id,
                    tool_name=event.tool_name,
                    arguments=event.arguments,
                )

            elif isinstance(event, StreamEnd):
                self.input_tokens = event.input_tokens
                self.output_tokens = event.output_tokens
                self.stop_reason = event.stop_reason

    def response(self) -> LLMResponse:
        return LLMResponse(
            text=self.text,
            tool_calls=self.tool_calls,
            thinking_blocks=self.thinking_blocks,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            stop_reason=self.stop_reason,
        )

# ──────────────────────────────────────────────
#  StreamingExecutor for ordered concurrent collection
# ──────────────────────────────────────────────

@dataclass
class _ToolExecResult:
    result: Optional[ToolResult]
    is_error: bool
    error_msg: str

class StreamingExecutor:
    """Collects concurrent tasks and returns them in submission order.

    Used by SubAgent and Teams to start tools early while keeping output order.
    """

    def __init__(self) -> None:
        self._tasks: list[tuple[int, asyncio.Task[Any]]] = []
        self._order = 0

    def submit(self, coro: AsyncGenerator[AgentEvent, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(self._wrap_coro(coro))
        self._tasks.append((self._order, task))
        self._order += 1
        return task

    async def _wrap_coro(
        self,
        coro: AsyncGenerator[AgentEvent, None],
    ) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        async for ev in coro:
            events.append(ev)
        return events

    async def collect_results(self) -> list[list[AgentEvent]]:
        """Wait for all tasks and return results in submission order."""
        if not self._tasks:
            return []
        ordered = sorted(self._tasks, key=lambda x: x[0])
        results: list[list[AgentEvent]] = []
        for idx, task in ordered:
            try:
                res = await task
                results.append(res)
            except Exception:
                results.append([])
        return results

# ──────────────────────────────────────────────
#  Agent class (main orchestrator)
# ──────────────────────────────────────────────

class Agent:
    """Orchestrates the ReAct loop: LLM → tools → results → repeat.

    Yields AgentEvents to the caller (TUI) as the loop progresses.
    Handles concurrency batching, permission checks, hooks, compression,
    max_tokens escalation, and Plan Mode reminders.
    """

    def __init__(
        self,
        client: Any,
        registry: Any,
        protocol: str,
        work_dir: str | Path = ".",
        max_iterations: int = 50,
        permission_checker: Any = None,
        context_window: int = 200_000,
        instructions_content: str = "",
        memory_manager: Any = None,
        hook_engine: Any = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.protocol = protocol
        self.work_dir = Path(work_dir)
        self.max_iterations = max_iterations
        self.permission_checker = permission_checker
        self.context_window = context_window
        self.instructions_content = instructions_content
        self.memory_manager = memory_manager
        self.hook_engine = hook_engine

        # Derived / mutable state
        if self.permission_checker:
            self.permission_mode = self.permission_checker.mode
        else:
            self.permission_mode = PermissionMode.DEFAULT
        self.coordinator_mode = False
        self.team_name: str = ""
        self._team_manager: Any = None
        self.session_dir = self._ensure_session_dir(self.work_dir)
        self.compact_breaker = self._create_compact_circuit_breaker()
        self.replacement_state: ContentReplacementState = create_replacement_state()
        self.recovery_state: RecoveryState = RecoveryState()
        self.agent_id = uuid.uuid4().hex[:12]
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._plan_path_cache: Optional[Path] = None
        self.active_skills: dict[str, str] = {}
        self._skill_catalog: str = ""
        self._agent_catalog: str = ""
        self._loop_count: int = 0
        self._extracting: bool = False

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        if self.permission_checker:
            self.permission_checker.mode = mode

    def activate_skill(self, name: str, prompt_body: str) -> None:
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        self.active_skills.clear()

    def set_skill_catalog(self, catalog: str) -> None:
        self._skill_catalog = catalog

    def set_agent_catalog(self, catalog: str) -> None:
        self._agent_catalog = catalog

    def _ensure_session_dir(self, work_dir: Path) -> Path:
        return ensure_session_dir(work_dir)

    def _create_compact_circuit_breaker(self) -> Any:
        """Create the compact circuit breaker if context module is available."""
        return CompactCircuitBreaker()

    def _get_plan_path(self) -> Path:
        """Lazy-singleton: generate a readable slug path the first time, cache it."""
        if self._plan_path_cache is not None:
            return self._plan_path_cache
        adj = random.choice(_ADJECTIVES)
        noun = random.choice(_NOUNS)
        stamp = datetime.datetime.now().strftime("%m%d-%H%M")
        slug = f"{adj}-{noun}-{stamp}.md"
        plans_dir = self.work_dir / ".mewcode" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        path = plans_dir / slug
        self._plan_path_cache = path
        return path

    def _build_hook_context(self, event: str, **kwargs: Any) -> Any:
        """Build a HookContext for hook execution."""
        from mewcode.hooks import HookContext
        tool_name = kwargs.get("tool_name", "")
        tool_args = kwargs.get("tool_args", {})
        if not tool_args and "tool_name" in kwargs:
            tool_args = {k: v for k, v in kwargs.items() if k not in ("tool_name", "iteration")}
        file_path = kwargs.get("file_path", "") or self._infer_file_path(kwargs)
        message = kwargs.get("message", "")
        error = kwargs.get("error", "")
        return HookContext(
            event_name=event,
            tool_name=tool_name,
            tool_args=tool_args,
            file_path=str(file_path) if file_path else "",
            message=message,
            error=error,
        )

    def _infer_file_path(self, args: dict[str, Any]) -> Optional[str]:
        """Extract a representative file path from tool arguments for hook matching.

        Checks: args["file_path"] → args["path"]. Returns first match, or None.
        """
        if "file_path" in args and args["file_path"]:
            return str(args["file_path"])
        if "path" in args and args["path"]:
            return str(args["path"])
        return None

    def _drain_hook_events(self) -> list[HookEvent]:
        """Drain notifications from hook engine and convert to AgentEvents."""
        if not self.hook_engine:
            return []
        return [HookEvent(hook_name=n.hook_id, message=n.output) for n in self.hook_engine.drain_notifications()]

    async def run(
        self,
        conversation: ConversationManager,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Main agent loop: async generator yielding AgentEvents.

        Flow:
        1. Increment iteration, check max_iterations
        2. _consume_mailbox (team messages)
        3. Apply tool result budget + auto_compact (layer 1 / layer 2)
        4. If plan mode, inject plan reminder
        5. Build system prompt with hooks
        6. Get tools schemas from registry
        7. client.stream() → StreamCollector.consume() → yield AgentEvents
        8. Accumulate tokens → yield UsageEvent
        9. Handle stop_reason == "max_tokens" (escalate + recover)
        10. If no tool calls → yield LoopComplete and exit
        11. If tool calls → partition into batches, execute, add results to conversation → yield TurnComplete
        """
        iteration = 0
        token_recoveries_used = 0
        consecutive_unknown = 0
        total_input = 0
        total_output = 0

        # Inject environment and long-term memory once at start
        from mewcode.context import get_long_term_memory
        from mewcode.prompts import build_environment_context
        env_ctx = build_environment_context(
            work_dir=str(self.work_dir),
            active_skills=self.active_skills if self.active_skills else None,
            skill_catalog=self._skill_catalog if self._skill_catalog else None,
            agent_catalog=self._agent_catalog if self._agent_catalog else None,
        )
        conversation.inject_environment(env_ctx)
        memory_content = ""
        if self.memory_manager:
            ltm = get_long_term_memory(self.memory_manager)
            if ltm:
                memory_content = ltm
        if self.instructions_content.strip() or memory_content.strip():
            conversation.inject_long_term_memory(self.instructions_content, memory_content)

        # Immediate memory extraction: if last user message contains memorable content
        if self.memory_manager and not self._extracting:
            for msg in reversed(conversation.history):
                if msg.role == "user" and msg.content:
                    if should_trigger_extraction(msg.content):
                        asyncio.ensure_future(self._extract_memories(conversation))
                    break

        # Trigger session_start hooks
        if self.hook_engine:
            ctx = self._build_hook_context("session_start")
            await self.hook_engine.run_hooks("session_start", ctx)
            for hev in self._drain_hook_events():
                yield hev

        while True:
            iteration += 1
            if iteration > self.max_iterations:
                yield ErrorEvent(f"Exceeded max_iterations={self.max_iterations}")
                break

            if self.hook_engine:
                ctx = self._build_hook_context("turn_start", iteration=iteration)
                await self.hook_engine.run_hooks("turn_start", ctx)
                for hev in self._drain_hook_events():
                    yield hev

            # Step 1: Consume team mailbox
            if self._team_manager:
                await self._consume_mailbox(conversation)

            # Step 2: Apply budget and auto-compact
            compacted = await self._apply_auto_compact(conversation)
            if compacted:
                pct = int(
                    conversation.last_input_tokens / self.context_window * 100
                )
                yield CompactNotification(
                    message=f"{compacted} (上下文占用: {conversation.last_input_tokens:,}/{self.context_window:,} tokens, {pct}%)"
                )

            # Trigger pre_send hook
            if self.hook_engine:
                ctx = self._build_hook_context("pre_send", iteration=iteration)
                await self.hook_engine.run_hooks("pre_send", ctx)
                for hev in self._drain_hook_events():
                    yield hev
                # Inject prompt messages from hooks into next LLM request
                prompt_msgs = self.hook_engine.get_prompt_messages()
                if prompt_msgs:
                    conversation.add_system_reminder("\n".join(prompt_msgs))

            # Step 3: Build system prompt
            from mewcode.prompts import build_system_prompt
            system_prompt = build_system_prompt(
                work_dir=str(self.work_dir),
                custom_instructions=self.instructions_content,
            )

            # Step 4: Plan mode reminder
            plan_path: Optional[Path] = None
            if self.permission_mode == PermissionMode.PLAN:
                plan_path = self._get_plan_path()
                plan_exists = plan_path.exists()
                if self.permission_checker:
                    self.permission_checker.plan_file_path = str(plan_path)
                from mewcode.prompts import build_plan_mode_reminder
                reminder = build_plan_mode_reminder(plan_path, plan_exists, iteration)
                conversation.add_system_reminder(reminder)

            # Step 5: Get enabled tool schemas
            schemas = self.registry.get_all_schemas(self.protocol)

            # Step 6: Apply tool result budget (Layer 1) right before stream
            api_conv, _new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            if _new_records:
                append_replacement_records(self.session_dir, _new_records)
                for rec in _new_records:
                    if rec.original_chars > 0:
                        yield PersistNotification(
                            tool_use_id=rec.tool_use_id,
                            original_chars=rec.original_chars,
                            preview_chars=len(rec.replacement),
                        )

            # Step 7: Stream LLM response
            collector = StreamCollector()
            stream = self.client.stream(api_conv, system=system_prompt, tools=schemas)
            async for ev in collector.consume(stream):
                yield ev

            # Step 7: Collect response and accumulate usage
            response = collector.response()
            total_input += response.input_tokens
            total_output += response.output_tokens
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens
            yield UsageEvent(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_input=total_input,
                total_output=total_output,
            )

            # Trigger post_receive hook
            if self.hook_engine:
                ctx = self._build_hook_context("post_receive")
                await self.hook_engine.run_hooks("post_receive", ctx)
                for hev in self._drain_hook_events():
                    yield hev

            # Step 8: Handle max_tokens stop reason → escalate
            if response.stop_reason == "max_tokens" and token_recoveries_used < MAX_OUTPUT_TOKENS_RECOVERIES:
                if hasattr(self.client, "set_max_output_tokens"):
                    self.client.set_max_output_tokens(MAX_TOKENS_CEILING)
                token_recoveries_used += 1
                yield RetryEvent(reason="max_tokens escalation")
                # Add the already generated text as assistant message and loop again
                conversation.add_assistant_message(
                    content=response.text,
                    tool_uses=response.tool_calls if response.tool_calls else None,
                    thinking_blocks=response.thinking_blocks if response.thinking_blocks else None,
                )
                conversation.add_system_reminder(
                    "Previous output hit max_tokens limit; continuing generation..."
                )
                continue

            # Step 9: Add assistant message to history
            conversation.add_assistant_message(
                content=response.text,
                tool_uses=response.tool_calls if response.tool_calls else None,
                thinking_blocks=response.thinking_blocks if response.thinking_blocks else None,
            )

            # Trigger memory extraction on interval (every N turns)
            self._loop_count += 1
            if self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0 and self.memory_manager and not self._extracting:
                asyncio.ensure_future(self._extract_memories(conversation))

            # Step 10: Check for termination
            if not response.tool_calls:
                if self.hook_engine:
                    ctx = self._build_hook_context("session_end")
                    await self.hook_engine.run_hooks("session_end", ctx)
                    for hev in self._drain_hook_events():
                        yield hev
                yield LoopComplete(stop_reason="end_turn" if not response.stop_reason else response.stop_reason)
                break

            # Step 11: Check consecutive unknown tools
            unknown_in_turn = sum(1 for tc in response.tool_calls if self.registry.get(tc.name) is None)
            if unknown_in_turn == len(response.tool_calls):
                consecutive_unknown += 1
                if consecutive_unknown >= 3:
                    yield ErrorEvent("Three consecutive turns with only unknown tools — stopping")
                    break
            else:
                consecutive_unknown = 0

            # Step 12: Partition tool calls into batches and execute
            batches = partition_tool_calls(response.tool_calls, self.registry)
            results: list[ToolResultBlock] = []

            for batch in batches:
                if batch.concurrent:
                    batch_results = await self._execute_batch_parallel(batch.calls)
                else:
                    batch_results = []
                    for tc in batch.calls:
                        async for ev in self._execute_tool(tc):
                            yield ev
                        # _execute_tool yields events and leaves last result in closure
                        # We need to collect it
                        # For simplicity, re-execute in direct mode (this is sequential batch anyway)
                        result = await self._execute_single_tool_direct(tc)
                        batch_results.append(result)

                for result in batch_results:
                    processed = self._maybe_persist_or_truncate(result.content)
                    results.append(
                        ToolResultBlock(
                            tool_use_id=result.tool_use_id,
                            content=processed,
                            is_error=result.is_error,
                        )
                    )
                    yield ToolResultEvent(
                        tool_id=result.tool_use_id,
                        tool_name=result.tool_name,
                        result=processed,
                        is_error=result.is_error,
                    )

            # Step 13: Add tool results to conversation
            conversation.add_tool_results_message(results)

            # Step 14: Trigger turn_end hooks
            if self.hook_engine:
                ctx = self._build_hook_context("turn_end", iteration=iteration)
                await self.hook_engine.run_hooks("turn_end", ctx)
                for hev in self._drain_hook_events():
                    yield hev

            # End of turn
            yield TurnComplete()

        # End of loop

    async def _consume_mailbox(self, conversation: ConversationManager) -> None:
        """Consume pending messages from team mailbox (if team_manager is set)."""
        if not self._team_manager:
            return
        messages = self._team_manager.mailbox().drain()
        for msg in messages:
            conversation.add_system_reminder(f"[team] {msg}")

    async def _apply_auto_compact(self, conversation: ConversationManager) -> Optional[str]:
        """Apply layer 1 (budget) and layer 2 (auto-compact) compression.

        Returns a notification string if compression happened, None otherwise.
        """
        changed2 = await auto_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            protocol=self.protocol,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
        )
        if changed2:
            return "Context compressed to fit within window; see sidebar for details."
        return None

    @dataclass
    class _DirectResult:
        tool_use_id: str
        tool_name: str
        content: str
        is_error: bool

    async def _execute_single_tool_direct(self, tc: ToolUseBlock) -> _DirectResult:
        """Execute a single tool directly without yielding events (for parallel batches)."""
        result = None
        is_error = False
        content = ""

        tool = self.registry.get(tc.name)
        if tool is None:
            content = f"Error: unknown tool \"{tc.name}\""
            is_error = True
        elif not self.registry.is_enabled(tc.name):
            content = f"Error: tool \"{tc.name}\" is disabled"
            is_error = True
        else:
            # Pre-tool hook (can reject)
            if self.hook_engine:
                ctx = self._build_hook_context("pre_tool_use", tool_name=tc.name, **tc.arguments)
                rejection = await self.hook_engine.run_pre_tool_hooks(ctx)
                if rejection is not None:
                    content = f"Hook rejected: {rejection.reason}"
                    is_error = True
                    tool = None

            if tool and not is_error:
                try:
                    params = tool.params_model.model_validate(tc.arguments)
                except Exception as e:
                    if tc.name.startswith("mcp_"):
                        params = tc.arguments
                        logger.debug(
                            "MCP tool %s param validation failed (%s), passing raw args",
                            tc.name, e,
                        )
                    else:
                        content = f"Parameter validation error for {tc.name}: {e}"
                        is_error = True
                        tool = None

            if tool and not is_error:
                try:
                    result = await tool.execute(params)
                    content = result.output
                    is_error = result.is_error
                    self._snapshot_for_recovery(tc, result)
                except Exception as e:
                    content = f"Tool execution error ({tc.name}): {e}"
                    is_error = True

            # Post-tool hook
            if self.hook_engine:
                ctx = self._build_hook_context("post_tool_use", tool_name=tc.name, **tc.arguments)
                await self.hook_engine.run_hooks("post_tool_use", ctx)

        return self._DirectResult(
            tool_use_id=tc.id,
            tool_name=tc.name,
            content=content,
            is_error=is_error,
        )

    async def _execute_batch_parallel(
        self,
        calls: list[ToolUseBlock],
    ) -> list[_DirectResult]:
        """Execute a batch of concurrent-safe tools in parallel."""
        tasks = [self._execute_single_tool_direct(tc) for tc in calls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _execute_tool(
        self,
        tc: ToolUseBlock,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute a single tool in sequential mode, handling permissions and HITL.

        This is the async generator path that yields PermissionRequest when needed.
        """
        tool = self.registry.get(tc.name)
        tool_name = tc.name
        args = tc.arguments

        if tool is None:
            yield ToolResultEvent(
                tool_id=tc.id,
                tool_name=tool_name,
                result=f"Error: unknown tool \"{tool_name}\"",
                is_error=True,
            )
            return

        if not self.registry.is_enabled(tc.name):
            yield ToolResultEvent(
                tool_id=tc.id,
                tool_name=tool_name,
                result=f"Error: tool \"{tool_name}\" is disabled",
                is_error=True,
            )
            return

        # Pre-tool hook
        if self.hook_engine:
            ctx = self._build_hook_context("pre_tool_use", tool_name=tc.name, **tc.arguments)
            rejection = await self.hook_engine.run_pre_tool_hooks(ctx)
            if rejection is not None:
                yield ToolResultEvent(
                    tool_id=tc.id,
                    tool_name=tool_name,
                    result=f"Hook rejected: {rejection.reason}",
                    is_error=True,
                )
                return
            for hev in self._drain_hook_events():
                yield hev

        # Permission check
        if self.permission_checker:
            decision = self.permission_checker.check(tool, args)
            if decision.effect == "deny":
                yield ToolResultEvent(
                    tool_id=tc.id,
                    tool_name=tool_name,
                    result=f"Permission denied: {decision.reason}",
                    is_error=True,
                )
                return
            elif decision.effect == "ask":
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                yield PermissionRequest(
                    tool_name=tool_name,
                    tool_args=args,
                    future=future,
                )
                response = await future
                if response == PermissionResponse.DENY:
                    yield ToolResultEvent(
                        tool_id=tc.id,
                        tool_name=tool_name,
                        result="Permission denied by user",
                        is_error=True,
                    )
                    return
                elif response == PermissionResponse.ALLOW_ALWAYS:
                    if hasattr(self.permission_checker, "rule_engine"):
                        content = extract_content(tool_name, args)
                        if len(content) > 60:
                            content = content[:60] + "*"
                        pattern = content + "*" if content else "*"
                        from mewcode.permissions.rules import Rule
                        self.permission_checker.rule_engine.append_local_rule(
                            Rule(tool_name=tool_name, pattern=pattern, effect="allow")
                        )

        # Validate parameters
        try:
            params = tool.params_model.model_validate(args)
        except Exception as e:
            if tool_name.startswith("mcp_"):
                params = args
                logger.debug(
                    "MCP tool %s param validation failed (%s), passing raw args",
                    tool_name, e,
                )
            else:
                yield ToolResultEvent(
                    tool_id=tc.id,
                    tool_name=tool_name,
                    result=f"Parameter validation error: {e}",
                    is_error=True,
                )
                return

        # Execute
        try:
            result: ToolResult = await tool.execute(params)
            self._snapshot_for_recovery(tc, result)
        except Exception as e:
            yield ToolResultEvent(
                tool_id=tc.id,
                tool_name=tool_name,
                result=f"Tool execution error: {e}",
                is_error=True,
            )
            return

        # Post-tool hook
        if self.hook_engine:
            ctx = self._build_hook_context("post_tool_use", tool_name=tc.name, **tc.arguments)
            await self.hook_engine.run_hooks("post_tool_use", ctx)
            for hev in self._drain_hook_events():
                yield hev

        processed = self._maybe_persist_or_truncate(result.output)
        yield ToolResultEvent(
            tool_id=tc.id,
            tool_name=tool_name,
            result=processed,
            is_error=result.is_error,
        )

    def _maybe_persist_or_truncate(self, output: str) -> str:
        """Persist large tool results to disk and return a preview, or truncate if still too big."""
        from mewcode.context import persist_tool_result, make_persisted_preview
        if len(output) > SINGLE_RESULT_CHAR_LIMIT:
            preview = persist_tool_result(output, self.session_dir)
            return make_persisted_preview(preview)
        elif len(output) > MAX_OUTPUT_CHARS:
            return output[:MAX_OUTPUT_CHARS] + "\n… (output truncated)"
        else:
            return output

    def _snapshot_for_recovery(self, tc: ToolUseBlock, result: ToolResult) -> None:
        if result.is_error or tc.name != "ReadFile":
            return
        file_path = tc.arguments.get("file_path") or tc.arguments.get("path")
        if not file_path:
            return
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            self.recovery_state.record_file_read(str(file_path), content)
        except OSError:
            pass

    async def manual_compact(
        self, conversation: ConversationManager
    ) -> Optional[str | CompactEvent]:
        from mewcode.context import manual_compact as _manual_compact
        result = await _manual_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            protocol=self.protocol,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
        )
        if result and self.memory_manager:
            memory_content = self.memory_manager.load()
            conversation.inject_long_term_memory(self.instructions_content, memory_content)
        return result

    async def _extract_memories(self, conversation: ConversationManager) -> None:
        if self._extracting:
            return
        self._extracting = True
        try:
            await self.memory_manager.extract(self.client, conversation)
        except Exception as e:
            logger.debug("Memory extraction error: %s", e)
        finally:
            self._extracting = False