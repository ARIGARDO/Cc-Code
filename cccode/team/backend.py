"""Execution backends for teammates.

Two flavours are supported in this file:

*   :class:`SpawnRequest` — the dataclass describing every teammate.
*   ``IN_PROCESS_BACKEND`` — asyncio-task based executor (always available).
*   ``TMUX_BACKEND`` — best-effort ``tmux split-window`` executor.

The iterm2 backend is intentionally omitted because we do not want to
couple the team module to Applescript.  If iterm2 is detected via the
$TERM_PROGRAM env variable the module still returns ``TmuxBackend`` — any
user on iTerm2 who has tmux installed gets the tmux path, and if they
do not have tmux they fall back to in-process.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from cccode.team.types import BackendType, InProcessTeammateNoSpawnError, TeammateCancelledError, TeammateInfo

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  SpawnRequest
# ──────────────────────────────────────────────

@dataclass
class SpawnRequest:
    team_name: str = ""
    member_name: str = ""
    agent_id: str = ""
    worktree_path: str = ""
    session_dir: str = ""
    agent_type: str = ""
    model: str = ""
    initial_prompt: str = ""
    plan_mode_required: bool = False
    # Environment / feature flags
    extra_env: dict[str, str] = field(default_factory=dict)
    # For in-process backend: the actual Agent-coroutine factory
    runnable: Callable[..., Any] | None = None


# ──────────────────────────────────────────────
#  In-Process backend
# ──────────────────────────────────────────────

class InProcessBackend:
    """Run teammates as asyncio tasks inside the host cccode process.

    This backend is always available and does not depend on tmux / iTerm2.
    It is the default fallback.  Its kill/wake primitives operate on
    ``asyncio.Task`` objects keyed by ``agent_id``.

    Because every teammate shares the same event loop, any teammate that
    tries to spawn a *sub*-teammate is rejected with
    :class:`InProcessTeammateNoSpawnError` — the team design expects the
    lead agent to own the spawn call.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._wake_events: dict[str, asyncio.Event] = {}
        self._lock = threading.Lock()
        self._host_member_name: str | None = None  # name of the member running *this* process; None == lead

    # ── setup ─────────────────────────────────
    def mark_host_as(self, member_name: str) -> None:
        self._host_member_name = member_name

    def host_member_name(self) -> str | None:
        return self._host_member_name

    def is_teammate_process(self) -> bool:
        return self._host_member_name is not None and self._host_member_name != "lead"

    # ── spawn / kill / wake ───────────────────
    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """Create a new asyncio task that runs ``req.runnable(req)``.

        Returns ``(pane_id, agent_id)`` — pane_id is a synthetic token
        ("inproc:<agent_id>") because there is no real terminal pane.

        Raises :class:`InProcessTeammateNoSpawnError` when called from
        within another teammate task.
        """

        if self.is_teammate_process():
            raise InProcessTeammateNoSpawnError(
                "In-process teammates cannot spawn further teammates "
                "(current member = %r)." % self._host_member_name
            )

        if not req.runnable:
            raise ValueError("InProcessBackend.spawn() requires req.runnable")

        pane_id = f"inproc:{req.agent_id}"

        loop = asyncio.get_event_loop()
        task = loop.create_task(req.runnable(req))
        with self._lock:
            self._tasks[req.agent_id] = task
            self._wake_events[req.agent_id] = asyncio.Event()

        logger.info("[team] spawned in-process teammate %s", req.member_name)

        # Attach a callback to clean up when the task finishes
        def _cleanup(fut: asyncio.Future) -> None:
            with self._lock:
                self._tasks.pop(req.agent_id, None)
                self._wake_events.pop(req.agent_id, None)
            try:
                fut.result()
            except asyncio.CancelledError:
                logger.info("[team] teammate %s cancelled", req.member_name)
            except Exception:
                logger.exception("[team] teammate %s crashed", req.member_name)

        task.add_done_callback(_cleanup)
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> bool:
        evt = self._wake_events.get(agent_id)
        if evt is None:
            return False
        evt.set()
        evt.clear()
        return True

    async def kill(self, agent_id: str) -> bool:
        task = self._tasks.get(agent_id)
        if task is None:
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except TeammateCancelledError:
            pass
        return True

    def agent_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._tasks.keys())


# ──────────────────────────────────────────────
#  Tmux backend
# ──────────────────────────────────────────────

class TmuxBackend:
    """Spawn teammates in new tmux panes.

    Each teammate becomes a new ``python -m cccode ...`` invocation
    running in a dedicated tmux pane.  We use ``tmux split-window`` so
    the user can visually observe the team; ``tmux send-keys`` is used
    for wake signalling.

    If ``tmux`` is not installed the methods are still safe to call —
    they log a warning and return a synthetic ``pane_id`` indicating the
    spawn was requested but not fulfilled.
    """

    def __init__(self, work_dir: str | None = None) -> None:
        self._work_dir = work_dir or os.getcwd()

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        pane_id = await self._send_spawn_command(req)
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> bool:
        if not pane_id or pane_id.startswith("tmux:missing"):
            return False
        pane_id_raw = pane_id.replace("tmux:", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", pane_id_raw, "Enter",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return True
        except FileNotFoundError:
            return False

    async def kill(self, pane_id: str, agent_id: str) -> bool:
        if not pane_id or pane_id.startswith("tmux:missing"):
            return False
        pane_id_raw = pane_id.replace("tmux:", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "kill-pane", "-t", pane_id_raw,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return True
        except FileNotFoundError:
            return False

    # ── internal ─────────────────────────────
    async def _send_spawn_command(self, req: SpawnRequest) -> str:
        if not self._has_tmux():
            logger.warning("[team] tmux not found; using in-process fallback")
            return "tmux:missing"

        cmd = [
            "python", "-m", "cccode",
            "--team", req.team_name,
            "--member", req.member_name,
            "--agent-id", req.agent_id,
            "--agent-type", req.agent_type or "teammate",
            "--worktree", req.worktree_path,
            "--session-dir", req.session_dir,
        ]
        if req.model:
            cmd += ["--model", req.model]
        if req.plan_mode_required:
            cmd += ["--plan-mode"]
        if req.initial_prompt:
            cmd += ["--prompt", req.initial_prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "split-window", "-d", "-P", "-F", "#{pane_id}",
                cwd=self._work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning("[team] tmux split-window failed: %s", stderr.decode(errors="ignore").strip())
                return "tmux:failed"

            pane_id = stdout.decode(errors="ignore").strip()
            if not pane_id:
                return "tmux:empty"

            # Send the command into the new pane
            await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", pane_id,
                " ".join(_quote_for_shell(c) for c in cmd), "Enter",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return f"tmux:{pane_id}"
        except FileNotFoundError:
            return "tmux:missing"
        except Exception:
            logger.exception("[team] tmux spawn failed")
            return "tmux:failed"

    def _has_tmux(self) -> bool:
        import shutil
        return shutil.which("tmux") is not None


# ── helpers ───────────────────────────────────────

def _quote_for_shell(part: str) -> str:
    if not part:
        return "''"
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.=/")
    if all(c in safe_chars for c in part):
        return part
    return "'" + part.replace("'", "'\\''") + "'"


def detect_backend(work_dir: str | None = None) -> Literal[BackendType.TMUX, BackendType.IN_PROCESS]:
    """Auto-detect the best teammate backend.

    *   tmux is preferred when available.
    *   Otherwise fall back to in-process (always works).
    """

    import shutil
    if shutil.which("tmux"):
        return BackendType.TMUX
    return BackendType.IN_PROCESS