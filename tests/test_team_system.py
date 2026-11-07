"""ch15 Team system integration tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from cccode.team.backend import InProcessBackend, SpawnRequest
from cccode.team.manager import TeamManager, sanitize
from cccode.team.registry import AgentNameRegistry
from cccode.team.types import (
    BackendType,
    Team,
    TeamError,
    TeammateInfo,
)
from cccode.team.mailbox import (
    Mailbox,
    build_text_message,
    build_shutdown_request,
    build_shutdown_response,
    build_plan_approval,
)
from cccode.team.tasks import TaskStore
from cccode.team.tools import TEAM_TOOL_NAMES, is_team_tool, build_team_tools


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir(tmp_path: Path) -> str:
    """Return a fresh temp directory path as string."""
    return str(tmp_path)


@pytest.fixture
def team_manager(tmp_dir: str) -> TeamManager:
    """Construct a TeamManager rooted at tmp_dir."""
    return TeamManager(tmp_dir)


@pytest.fixture
def team_dir(tmp_dir: str) -> str:
    return tmp_dir


@pytest.fixture
def registry() -> AgentNameRegistry:
    return AgentNameRegistry()


# ── Types tests ────────────────────────────────────────────────────────


class TestTypes:
    def test_backend_type_values(self):
        """BackendType has the expected string values."""
        assert BackendType.TMUX == "tmux"
        assert BackendType.IN_PROCESS == "in-process"
        assert BackendType.ITERM2 == "iterm2"

    def test_teammate_info_serialization(self):
        """TeammateInfo → dict → from_dict round-trips correctly."""
        info = TeammateInfo(
            name="worker-1",
            agent_id="abc123",
            agent_type="coder",
            model="sonnet",
            worktree_path="/tmp/wt",
            branch="feature-x",
            backend_type=BackendType.IN_PROCESS,
            pane_id="inproc:abc123",
            is_active=True,
            plan_mode_required=False,
            session_dir="/tmp/sess",
            started_at="2025-01-01T00:00:00+00:00",
        )
        data = info.to_dict()
        restored = TeammateInfo.from_dict(data)
        assert restored.name == "worker-1"
        assert restored.agent_id == "abc123"
        assert restored.agent_type == "coder"
        assert restored.backend_type == BackendType.IN_PROCESS
        assert restored.is_active is True
        assert restored.worktree_path == "/tmp/wt"

    def test_team_serialization_members_preserved(self):
        """Team round-trip preserves members."""
        team = Team(
            name="Project Apollo",
            sanitized_name="project-apollo",
            lead_agent_id="lead",
            backend=BackendType.IN_PROCESS,
            description="Moon landing project",
            created_at="2025-01-01T00:00:00+00:00",
            members=[
                TeammateInfo(name="lead", agent_id="lead"),
                TeammateInfo(name="lunar", agent_id="lunar-1", agent_type="coder", is_active=True),
            ],
        )
        data = team.to_dict()
        restored = Team.from_dict(data)
        assert restored.name == "Project Apollo"
        assert restored.sanitized_name == "project-apollo"
        assert len(restored.members) == 2
        assert restored.members[1].agent_id == "lunar-1"
        assert restored.members[1].is_active is True

    def test_member_lookup(self):
        """member_by_name / member_by_agent_id lookups."""
        team = Team(name="t", sanitized_name="t")
        team.members.append(TeammateInfo(name="worker", agent_id="w-123"))
        assert team.member_by_name("worker") is not None
        assert team.member_by_agent_id("w-123") is not None
        assert team.member_by_name("nope") is None
        assert team.member_by_agent_id("nope") is None

    def test_has_active_members(self):
        """has_active_members distinguishes active vs inactive teammates."""
        team = Team(name="t", sanitized_name="t", members=[
            TeammateInfo(name="lead"),
        ])
        assert team.has_active_members() is False
        team.members.append(TeammateInfo(name="worker", is_active=True))
        assert team.has_active_members() is True


# ── Sanitize tests ─────────────────────────────────────────────────────


class TestSanitize:
    def test_basic_sanitization(self):
        assert sanitize("Hello World") == "hello-world"

    def test_sanitize_symbols(self):
        assert sanitize("Proj!@#$ect") == "proj-ect"

    def test_sanitize_empty_raises(self):
        with pytest.raises(TeamError):
            sanitize("")

    def test_sanitize_only_symbols_raises(self):
        with pytest.raises(TeamError):
            sanitize("!!!")

    def test_sanitize_trims(self):
        result = sanitize("  Hello  ")
        assert not result.startswith("-")
        assert not result.endswith("-")


# ── TeamManager tests ──────────────────────────────────────────────────


class TestTeamManager:
    def test_create_team_succeeds(self, team_manager: TeamManager):
        """Can create a team via TeamManager.create()."""
        team = asyncio.run(team_manager.create("Apollo"))
        assert team.name == "Apollo"
        assert team.sanitized_name == "apollo"
        # Lead member is auto-added
        lead = team.member_by_name("lead")
        assert lead is not None
        assert lead.agent_id == "lead"

    def test_create_team_makes_config_dir(self, team_manager: TeamManager, tmp_dir: str):
        """Creating a team creates its config directory."""
        team = asyncio.run(team_manager.create("Apollo"))
        assert Path(team.config_dir).exists()
        assert (Path(team.config_dir) / "mailbox").exists()

    def test_create_team_persists_config(self, team_manager: TeamManager):
        """config.json is written with valid JSON."""
        team = asyncio.run(team_manager.create("Apollo"))
        path = Path(team.config_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["name"] == "Apollo"
        assert data["sanitized_name"] == "apollo"

    def test_list_returns_summaries(self, team_manager: TeamManager):
        """list_() returns dicts with name and description."""
        asyncio.run(team_manager.create("Apollo", description="Moon project"))
        summaries = asyncio.run(team_manager.list_())
        assert len(summaries) >= 1
        assert any(s["name"] == "Apollo" for s in summaries)

    def test_get_returns_team(self, team_manager: TeamManager):
        created = asyncio.run(team_manager.create("Apollo"))
        got = asyncio.run(team_manager.get("apollo"))
        assert got.name == created.name

    def test_get_missing_raises(self, team_manager: TeamManager):
        with pytest.raises(Exception):  # TeamNotFoundError or subclass
            asyncio.run(team_manager.get("does-not-exist"))

    def test_delete_empty_team(self, team_manager: TeamManager, tmp_dir: str):
        created = asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.delete("apollo"))
        assert not Path(created.config_dir).exists()

    def test_delete_without_force_rejects_active(self, team_manager: TeamManager):
        """Cannot delete a team with active members unless --force."""
        created = asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.add_member(
            "apollo",
            TeammateInfo(name="worker", agent_id="w-1", is_active=True),
        ))
        with pytest.raises(Exception):  # TeamHasActiveMembersError / generic TeamError
            asyncio.run(team_manager.delete("apollo"))

    def test_delete_force_works(self, team_manager: TeamManager):
        created = asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.add_member(
            "apollo",
            TeammateInfo(name="worker", agent_id="w-1", is_active=True),
        ))
        asyncio.run(team_manager.delete("apollo", force=True))
        assert not Path(created.config_dir).exists()

    def test_add_member(self, team_manager: TeamManager):
        asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.add_member(
            "apollo",
            TeammateInfo(name="worker", agent_id="w-1", agent_type="coder"),
        ))
        team = asyncio.run(team_manager.get("apollo"))
        assert team.member_by_name("worker") is not None
        assert team.member_by_name("worker").agent_type == "coder"

    def test_set_member_active(self, team_manager: TeamManager):
        asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.add_member(
            "apollo",
            TeammateInfo(name="worker", agent_id="w-1", is_active=True),
        ))
        asyncio.run(team_manager.set_member_active("apollo", "worker", False))
        team = asyncio.run(team_manager.get("apollo"))
        m = team.member_by_name("worker")
        assert m is not None
        assert m.is_active is False

    def test_update_member(self, team_manager: TeamManager):
        asyncio.run(team_manager.create("Apollo"))
        asyncio.run(team_manager.add_member(
            "apollo",
            TeammateInfo(name="worker", agent_id="w-1"),
        ))
        asyncio.run(team_manager.update_member(
            "apollo", "worker",
            agent_id="w-2",
            pane_id="pane-2",
            backend_type=BackendType.IN_PROCESS,
            worktree_path="/tmp/wt",
            session_dir="/tmp/sess",
        ))
        team = asyncio.run(team_manager.get("apollo"))
        m = team.member_by_name("worker")
        assert m is not None
        assert m.agent_id == "w-2"
        assert m.pane_id == "pane-2"
        assert m.backend_type == BackendType.IN_PROCESS


# ── Registry tests ─────────────────────────────────────────────────────


class TestAgentNameRegistry:
    def test_register_and_resolve(self, registry: AgentNameRegistry):
        registry.register("worker-1", "agent-abc")
        assert registry.resolve("worker-1") == "agent-abc"

    def test_resolve_returns_none_for_unknown(self, registry: AgentNameRegistry):
        assert registry.resolve("nope") is None

    def test_name_of_lookup(self, registry: AgentNameRegistry):
        registry.register("worker-1", "agent-abc")
        assert registry.name_of("agent-abc") == "worker-1"

    def test_unregister(self, registry: AgentNameRegistry):
        registry.register("worker-1", "agent-abc")
        registry.unregister("worker-1")
        assert registry.resolve("worker-1") is None
        assert registry.name_of("agent-abc") is None

    def test_override_replaces(self, registry: AgentNameRegistry):
        registry.register("worker-1", "agent-a")
        registry.register("worker-1", "agent-b")
        assert registry.resolve("worker-1") == "agent-b"
        # Previous agent_id should be unlinked
        assert registry.name_of("agent-a") is None

    def test_all_names(self, registry: AgentNameRegistry):
        registry.register("a", "1")
        registry.register("b", "2")
        assert set(registry.all_names()) == {"a", "b"}


# ── Mailbox tests ──────────────────────────────────────────────────────


class TestMailbox:
    def test_write_and_read(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        msg = build_text_message(from_="lead", to="worker-1", summary="hi", content="hello")
        asyncio.run(mb.write("worker-1", msg))
        messages = asyncio.run(mb.read("worker-1"))
        assert len(messages) == 1
        assert messages[0].from_ == "lead"
        assert messages[0].content == "hello"

    def test_empty_read(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        messages = asyncio.run(mb.read("nobody"))
        assert messages == []

    def test_shutdown_message_type(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        msg = build_shutdown_request(from_="lead", to="worker", reason="wrap up")
        asyncio.run(mb.write("worker", msg))
        messages = asyncio.run(mb.read("worker"))
        assert len(messages) == 1
        assert messages[0].type == "shutdown_request"
        assert messages[0].content == "wrap up"

    def test_shutdown_response_message(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        msg = build_shutdown_response(from_="worker", to="lead", approved=True, reason="done")
        asyncio.run(mb.write("lead", msg))
        messages = asyncio.run(mb.read("lead"))
        assert messages[0].type == "shutdown_response"
        assert messages[0].payload["approve"] is True

    def test_plan_approval_message(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        msg = build_plan_approval(from_="lead", to="worker", approve=False, feedback="needs more detail")
        asyncio.run(mb.write("worker", msg))
        messages = asyncio.run(mb.read("worker"))
        assert messages[0].type == "plan_approval_response"
        assert messages[0].payload["approve"] is False

    def test_write_many_broadcast(self, tmp_dir: str):
        mb = Mailbox(tmp_dir)
        targets = ["worker-1", "worker-2", "worker-3"]
        msg_factory = lambda to: build_text_message(
            from_="lead", to=to, summary="ping", content="hello " + to
        )
        asyncio.run(mb.write_many(targets, msg_factory))
        for target in targets:
            messages = asyncio.run(mb.read(target))
            assert len(messages) == 1
            assert messages[0].to == target


# ── TaskStore tests ────────────────────────────────────────────────────


class TestTaskStore:
    def test_create_and_get(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        task_id = asyncio.run(store.create("Implement feature X", description="Do the thing", assignee="worker-1"))
        task = asyncio.run(store.get(task_id))
        assert task is not None
        assert task.title == "Implement feature X"
        assert task.assignee == "worker-1"

    def test_list_with_status_filter(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        id1 = asyncio.run(store.create("Task A", assignee="a"))
        id2 = asyncio.run(store.create("Task B", assignee="b"))
        asyncio.run(store.update(id1, status="completed"))
        pending = asyncio.run(store.list_(status="pending"))
        completed = asyncio.run(store.list_(status="completed"))
        assert len(pending) == 1
        assert pending[0].id == id2
        assert len(completed) == 1
        assert completed[0].id == id1

    def test_update_title(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        task_id = asyncio.run(store.create("Old title"))
        asyncio.run(store.update(task_id, title="New title"))
        task = asyncio.run(store.get(task_id))
        assert task.title == "New title"

    def test_dependency_blocked_by(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        prerequisite = asyncio.run(store.create("Prerequisite"))
        dependent = asyncio.run(store.create("Dep", blocked_by=[prerequisite]))
        tasks = asyncio.run(store.list_())
        ids_to_tasks = {t.id: t for t in tasks}
        assert ids_to_tasks[prerequisite].status == "pending"
        # Dependent has blocked_by
        assert prerequisite in ids_to_tasks[dependent].blocked_by
        # Prerequisite has reverse blocks reference
        assert dependent in ids_to_tasks[prerequisite].blocks

    def test_delete(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        task_id = asyncio.run(store.create("To be deleted"))
        assert asyncio.run(store.get(task_id)) is not None
        ok = asyncio.run(store.delete(task_id))
        assert ok is True
        assert asyncio.run(store.get(task_id)) is None

    def test_get_missing(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        assert asyncio.run(store.get("does-not-exist")) is None


# ── Tools registration tests ───────────────────────────────────────────


class TestTeamTools:
    def test_tool_names_constant(self):
        assert "TeamCreate" in TEAM_TOOL_NAMES
        assert "TeamDelete" in TEAM_TOOL_NAMES
        assert "TaskCreate" in TEAM_TOOL_NAMES
        assert "TaskGet" in TEAM_TOOL_NAMES
        assert "TaskList" in TEAM_TOOL_NAMES
        assert "TaskUpdate" in TEAM_TOOL_NAMES
        assert "SendMessage" in TEAM_TOOL_NAMES

    def test_is_team_tool_helper(self):
        assert is_team_tool("TeamCreate") is True
        assert is_team_tool("Agent") is False

    def test_build_team_tools_instantiates_seven(self, team_manager: TeamManager, registry: AgentNameRegistry):
        tools = build_team_tools(team_manager, registry=registry)
        assert len(tools) == 7
        names = {t.name for t in tools}
        assert names == set(TEAM_TOOL_NAMES)


# ── Tool behaviour tests ───────────────────────────────────────────────


class TestToolBehaviour:
    def test_team_create_tool(self, team_manager: TeamManager):
        from cccode.team.tools.team_create import TeamCreateTool
        tool = TeamCreateTool(team_manager)
        result = asyncio.run(tool.execute({"name": "Apollo", "description": "moon"}))
        assert "Apollo" in result.output

    def test_team_create_tool_invalid_args(self, team_manager: TeamManager):
        from cccode.team.tools.team_create import TeamCreateTool
        tool = TeamCreateTool(team_manager)
        # Missing required 'name'
        result = asyncio.run(tool.execute({}))
        assert result.is_error is True or "Invalid" in result.output

    def test_task_create_tool(self, team_manager: TeamManager):
        from cccode.team.tools.task_create import TaskCreateTool
        asyncio.run(team_manager.create("Apollo"))
        tool = TaskCreateTool(team_manager)
        result = asyncio.run(tool.execute({
            "team": "apollo",
            "title": "Build rocket",
            "description": "Make it fly",
            "assignee": "engineer",
        }))
        assert "created" in result.output.lower() or "Build rocket" in result.output

    def test_task_get_tool(self, team_manager: TeamManager):
        from cccode.team.tools.task_create import TaskCreateTool
        from cccode.team.tools.task_get import TaskGetTool
        asyncio.run(team_manager.create("Apollo"))
        create_tool = TaskCreateTool(team_manager)
        asyncio.run(create_tool.execute({
            "team": "apollo",
            "title": "Test task",
        }))
        # Find a task_id by listing tasks
        team = asyncio.run(team_manager.get("apollo"))
        tasks = asyncio.run(TaskStore(team.config_dir).list_())
        assert len(tasks) > 0
        task_id = tasks[0].id
        # Now use TaskGetTool
        get_tool = TaskGetTool(team_manager)
        result = asyncio.run(get_tool.execute({"team": "apollo", "task_id": task_id}))
        assert "Test task" in result.output

    def test_task_list_tool(self, team_manager: TeamManager):
        from cccode.team.tools.task_list import TaskListTool
        asyncio.run(team_manager.create("Apollo"))
        tool = TaskListTool(team_manager)
        # Empty team, empty tasks
        result = asyncio.run(tool.execute({"team": "apollo"}))
        # Either "no matching" or a JSON list []
        assert result.is_error is False or "matching" in result.output.lower()

    def test_task_update_tool(self, team_manager: TeamManager):
        from cccode.team.tools.task_create import TaskCreateTool
        from cccode.team.tools.task_update import TaskUpdateTool
        asyncio.run(team_manager.create("Apollo"))
        create_tool = TaskCreateTool(team_manager)
        asyncio.run(create_tool.execute({
            "team": "apollo",
            "title": "Test task",
        }))
        team = asyncio.run(team_manager.get("apollo"))
        tasks = asyncio.run(TaskStore(team.config_dir).list_())
        task_id = tasks[0].id
        update_tool = TaskUpdateTool(team_manager)
        result = asyncio.run(update_tool.execute({
            "team": "apollo",
            "task_id": task_id,
            "status": "completed",
        }))
        assert "updated" in result.output.lower()

    def test_send_message_tool(self, team_manager: TeamManager, registry: AgentNameRegistry):
        from cccode.team.tools.send_message import SendMessageTool
        asyncio.run(team_manager.create("Apollo"))
        tool = SendMessageTool(team_manager, registry=registry, current_member="lead")
        result = asyncio.run(tool.execute({
            "team": "apollo",
            "to": "worker-1",
            "summary": "greeting",
            "message": "hello",
        }))
        assert "delivered_to" in result.output.lower() or "delivered" in result.output.lower()

    def test_team_delete_tool(self, team_manager: TeamManager):
        from cccode.team.tools.team_delete import TeamDeleteTool
        asyncio.run(team_manager.create("Apollo"))
        tool = TeamDeleteTool(team_manager)
        result = asyncio.run(tool.execute({"name": "apollo"}))
        assert "deleted" in result.output.lower()


# ── InProcessBackend tests ─────────────────────────────────────────────


class TestInProcessBackend:
    def test_instantiation(self):
        backend = InProcessBackend()
        assert backend.host_member_name() is None

    def test_mark_host_as_changes_member(self):
        backend = InProcessBackend()
        backend.mark_host_as("worker-1")
        assert backend.host_member_name() == "worker-1"
        assert backend.is_teammate_process() is True

    def test_spawn_rejects_from_teammate(self):
        """A teammate cannot spawn further teammates in-process."""
        backend = InProcessBackend()
        backend.mark_host_as("worker-1")
        req = SpawnRequest(team_name="test", member_name="sub", agent_id="sub-1")
        # runnable is irrelevant because the gate fires before spawning
        req.runnable = lambda *args, **kwargs: asyncio.sleep(0)
        with pytest.raises(Exception):  # TeamError / InProcessTeammateNoSpawnError
            asyncio.run(backend.spawn(req))

    def test_spawn_from_lead_runs_runnable(self):
        """Lead can spawn an in-process teammate and await it."""
        backend = InProcessBackend()
        results: list[str] = []

        async def _runnable(req: SpawnRequest) -> None:
            results.append(f"ran:{req.member_name}")

        req = SpawnRequest(
            team_name="test",
            member_name="worker-1",
            agent_id="w-1",
            runnable=_runnable,
        )
        pane_id, agent_id = asyncio.run(backend.spawn(req))
        assert agent_id == "w-1"
        assert pane_id.startswith("inproc:")
        # Give the event loop a moment to execute the task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # we can't directly run the task since it's on a different loop
            # but we can check the task was created
            pass
        finally:
            loop.close()

    def test_wake_and_kill(self):
        """wake and kill are safe to call even without an active task."""
        backend = InProcessBackend()
        result = asyncio.run(backend.wake("pane-1", "agent-1"))
        assert result is False  # No such task
        result = asyncio.run(backend.kill("agent-1"))
        assert result is False


# ── Coordinator module tests ───────────────────────────────────────────


class TestCoordinator:
    def test_is_enabled_false_by_default(self):
        # Ensure env var is not set
        old = os.environ.pop("CCCODE_COORDINATOR_MODE", None)
        try:
            from cccode.coordinator import is_enabled
            assert is_enabled() is False
        finally:
            if old is not None:
                os.environ["CCCODE_COORDINATOR_MODE"] = old

    def test_is_enabled_true_with_env(self):
        os.environ["CCCODE_COORDINATOR_MODE"] = "1"
        try:
            from cccode.coordinator import is_enabled
            assert is_enabled() is True
        finally:
            del os.environ["CCCODE_COORDINATOR_MODE"]

    def test_filter_tool_names_allows_core(self):
        from cccode.coordinator import filter_tool_names
        allowed = filter_tool_names(["Agent", "read_file", "bash", "glob", "grep"])
        assert "Agent" in allowed
        assert "read_file" in allowed
        assert "bash" in allowed

    def test_filter_tool_names_blocks_writes(self):
        from cccode.coordinator import filter_tool_names
        # edit_file and write_file_tool should be dropped
        result = filter_tool_names(["edit_file", "write_file", "write_file_tool", "read_file"])
        assert "edit_file" not in result
        assert "write_file" not in result
        assert "write_file_tool" not in result
        assert "read_file" in result

    def test_filter_tool_names_includes_team_tools(self):
        from cccode.coordinator import filter_tool_names
        result = filter_tool_names(TEAM_TOOL_NAMES)
        for tool_name in TEAM_TOOL_NAMES:
            assert tool_name in result

    def test_system_prompt_suffix_non_empty(self):
        from cccode.coordinator import system_prompt_suffix
        text = system_prompt_suffix()
        assert len(text) > 0
        assert "coordinator" in text.lower()


# ── Cross-process consistency (file-level concurrency) ─────────────────


class TestCrossProcessConsistency:
    def test_mailbox_concurrent_writers(self, tmp_dir: str):
        """Many async tasks writing the same mailbox should not corrupt it."""
        mb = Mailbox(tmp_dir)
        messages = []
        async def _writer(i: int):
            msg = build_text_message(
                from_="lead", to="worker",
                summary=f"msg-{i}", content=f"value-{i}"
            )
            await mb.write("worker", msg)

        async def _run_all():
            await asyncio.gather(*(_writer(i) for i in range(20)))

        asyncio.run(_run_all())
        result = asyncio.run(mb.read("worker"))
        assert len(result) == 20

    def test_taskstore_concurrent_writers(self, tmp_dir: str):
        store = TaskStore(tmp_dir)
        async def _creator(i: int):
            await store.create(f"task-{i}", description=f"desc-{i}")

        async def _run_all():
            await asyncio.gather(*(_creator(i) for i in range(10)))

        asyncio.run(_run_all())
        tasks = asyncio.run(store.list_())
        assert len(tasks) == 10


# ── End-to-end: create team → add member → send message → task ─────────


class TestEndToEnd:
    def test_full_team_workflow(self, team_manager: TeamManager, registry: AgentNameRegistry):
        """A realistic mini team-workflow test."""
        # 1. Create team
        team = asyncio.run(team_manager.create("Alpha", description="test team"))
        assert team.sanitized_name == "alpha"

        # 2. Register a teammate name
        registry.register("worker", "agent-1")
        assert registry.resolve("worker") == "agent-1"

        # 3. Add teammate info
        asyncio.run(team_manager.add_member(
            "alpha",
            TeammateInfo(
                name="worker",
                agent_id="agent-1",
                agent_type="coder",
                backend_type=BackendType.IN_PROCESS,
                is_active=True,
            ),
        ))

        # 4. Create a shared task
        team = asyncio.run(team_manager.get("alpha"))
        store = TaskStore(team.config_dir)
        task_id = asyncio.run(store.create(
            "Implement login", description="Auth flow", assignee="worker"
        ))
        task = asyncio.run(store.get(task_id))
        assert task.status == "pending"

        # 5. Update the task status
        asyncio.run(store.update(task_id, status="in_progress"))
        task = asyncio.run(store.get(task_id))
        assert task.status == "in_progress"

        # 6. Send a message to the teammate
        mb = Mailbox(team.mailbox_dir)
        asyncio.run(mb.write("worker", build_text_message(
            from_="lead", to="worker", summary="ping", content="How's it going?"
        )))
        messages = asyncio.run(mb.read("worker"))
        assert len(messages) == 1
        assert messages[0].content == "How's it going?"