"""Direct test runner for ch15 Team system.

Bypasses shell command length issue by invoking Python directly.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Ensure mewcode is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mewcode.team.backend import InProcessBackend, SpawnRequest
from mewcode.team.manager import TeamManager, sanitize
from mewcode.team.registry import AgentNameRegistry
from mewcode.team.types import (
    BackendType,
    Team,
    TeamError,
    TeammateInfo,
)
from mewcode.team.mailbox import (
    Mailbox,
    build_text_message,
    build_shutdown_request,
    build_shutdown_response,
    build_plan_approval,
)
from mewcode.team.tasks import TaskStore
from mewcode.team.tools import TEAM_TOOL_NAMES, is_team_tool, build_team_tools
import os


class TestReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[tuple[str, str]] = []

    def ok(self, name: str):
        self.passed += 1
        print(f"  ✓ {name}")

    def fail(self, name: str, error: str):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  ✗ {name}: {error}")


def _tmp_dir() -> str:
    d = tempfile.mkdtemp(prefix="mewcode-team-")
    return d


def run_all() -> TestReport:
    report = TestReport()
    print("Running ch15 Team system tests...\n")

    # ── Types ─────────────────────────────────────
    print("[Types]")
    try:
        assert BackendType.TMUX == "tmux"
        assert BackendType.IN_PROCESS == "in-process"
        assert BackendType.ITERM2 == "iterm2"
        report.ok("BackendType values")
    except Exception as e:
        report.fail("BackendType values", str(e))

    try:
        info = TeammateInfo(
            name="worker-1", agent_id="abc123", agent_type="coder",
            model="sonnet", worktree_path="/tmp/wt", branch="feature-x",
            backend_type=BackendType.IN_PROCESS, pane_id="inproc:abc123",
            is_active=True, plan_mode_required=False, session_dir="/tmp/sess",
            started_at="2025-01-01T00:00:00+00:00",
        )
        data = info.to_dict()
        restored = TeammateInfo.from_dict(data)
        assert restored.name == "worker-1"
        assert restored.agent_id == "abc123"
        assert restored.backend_type == BackendType.IN_PROCESS
        assert restored.is_active is True
        report.ok("TeammateInfo round-trip")
    except Exception as e:
        report.fail("TeammateInfo round-trip", str(e))

    try:
        team = Team(
            name="Project Apollo", sanitized_name="project-apollo",
            lead_agent_id="lead", backend=BackendType.IN_PROCESS,
            description="Moon landing project", created_at="2025-01-01T00:00:00+00:00",
            members=[
                TeammateInfo(name="lead", agent_id="lead"),
                TeammateInfo(name="lunar", agent_id="lunar-1", agent_type="coder", is_active=True),
            ],
        )
        data = team.to_dict()
        restored = Team.from_dict(data)
        assert restored.name == "Project Apollo"
        assert len(restored.members) == 2
        report.ok("Team serialization preserves members")
    except Exception as e:
        report.fail("Team serialization", str(e))

    try:
        team = Team(name="t", sanitized_name="t")
        team.members.append(TeammateInfo(name="worker", agent_id="w-123"))
        assert team.member_by_name("worker") is not None
        assert team.member_by_agent_id("w-123") is not None
        assert team.member_by_name("nope") is None
        report.ok("Member lookup helpers")
    except Exception as e:
        report.fail("Member lookup helpers", str(e))

    try:
        team = Team(name="t", sanitized_name="t", members=[TeammateInfo(name="lead")])
        assert team.has_active_members() is False
        team.members.append(TeammateInfo(name="worker", is_active=True))
        assert team.has_active_members() is True
        report.ok("has_active_members")
    except Exception as e:
        report.fail("has_active_members", str(e))

    # ── Sanitize ──────────────────────────────────
    print("\n[Sanitize]")
    try:
        assert sanitize("Hello World") == "hello-world"
        assert sanitize("Proj!@#$ect") == "proj-ect"
        report.ok("basic sanitization")
    except Exception as e:
        report.fail("basic sanitization", str(e))

    try:
        for bad in ["", "   ", "!!!"]:
            try:
                sanitize(bad)
                raise AssertionError(f"expected TeamError for {bad!r}")
            except TeamError:
                pass
        report.ok("invalid names rejected")
    except Exception as e:
        report.fail("invalid names rejected", str(e))

    # ── TeamManager ───────────────────────────────
    print("\n[TeamManager]")
    try:
        tm = TeamManager(_tmp_dir())
        team = asyncio.run(tm.create("Apollo"))
        assert team.name == "Apollo"
        assert team.sanitized_name == "apollo"
        assert team.member_by_name("lead") is not None
        report.ok("create() basic")
    except Exception as e:
        report.fail("create() basic", str(e))

    try:
        tmp = _tmp_dir()
        tm = TeamManager(tmp)
        team = asyncio.run(tm.create("Apollo"))
        assert Path(team.config_dir).exists()
        assert (Path(team.config_dir) / "mailbox").exists()
        assert Path(team.config_path).exists()
        data = json.loads(Path(team.config_path).read_text())
        assert data["name"] == "Apollo"
        report.ok("persistence layout")
    except Exception as e:
        report.fail("persistence layout", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo", description="Moon"))
        summaries = asyncio.run(tm.list_())
        assert any(s["name"] == "Apollo" for s in summaries)
        report.ok("list_() returns summaries")
    except Exception as e:
        report.fail("list_()", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        created = asyncio.run(tm.create("Apollo"))
        got = asyncio.run(tm.get("apollo"))
        assert got.name == created.name
        report.ok("get() loads team")
    except Exception as e:
        report.fail("get()", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        got = False
        try:
            asyncio.run(tm.get("nope"))
            got = True
        except Exception:
            pass
        assert not got
        report.ok("get() missing raises")
    except Exception as e:
        report.fail("get() missing", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        team = asyncio.run(tm.create("Apollo"))
        asyncio.run(tm.delete("apollo"))
        assert not Path(team.config_dir).exists()
        report.ok("delete() empty team")
    except Exception as e:
        report.fail("delete() empty team", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        asyncio.run(tm.add_member("apollo", TeammateInfo(name="worker", agent_id="w-1", is_active=True)))
        failed = False
        try:
            asyncio.run(tm.delete("apollo"))
        except Exception:
            failed = True
        assert failed, "should have rejected delete of team with active members"
        report.ok("delete() rejects active members")
    except Exception as e:
        report.fail("delete() rejects active members", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        team = asyncio.run(tm.create("Apollo"))
        asyncio.run(tm.add_member("apollo", TeammateInfo(name="worker", agent_id="w-1", is_active=True)))
        asyncio.run(tm.delete("apollo", force=True))
        assert not Path(team.config_dir).exists()
        report.ok("delete() force works")
    except Exception as e:
        report.fail("delete() force", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        asyncio.run(tm.add_member("apollo", TeammateInfo(name="worker", agent_id="w-1", agent_type="coder")))
        team = asyncio.run(tm.get("apollo"))
        m = team.member_by_name("worker")
        assert m is not None and m.agent_type == "coder"
        report.ok("add_member()")
    except Exception as e:
        report.fail("add_member()", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        asyncio.run(tm.add_member("apollo", TeammateInfo(name="worker", agent_id="w-1", is_active=True)))
        asyncio.run(tm.set_member_active("apollo", "worker", False))
        team = asyncio.run(tm.get("apollo"))
        m = team.member_by_name("worker")
        assert m.is_active is False
        report.ok("set_member_active()")
    except Exception as e:
        report.fail("set_member_active()", str(e))

    # ── Registry ──────────────────────────────────
    print("\n[AgentNameRegistry]")
    try:
        reg = AgentNameRegistry()
        reg.register("worker-1", "agent-abc")
        assert reg.resolve("worker-1") == "agent-abc"
        assert reg.name_of("agent-abc") == "worker-1"
        assert reg.resolve("nope") is None
        reg.unregister("worker-1")
        assert reg.resolve("worker-1") is None
        report.ok("register/resolve/unregister")
    except Exception as e:
        report.fail("register/resolve/unregister", str(e))

    try:
        reg = AgentNameRegistry()
        reg.register("worker-1", "agent-a")
        reg.register("worker-1", "agent-b")
        assert reg.resolve("worker-1") == "agent-b"
        assert reg.name_of("agent-a") is None
        report.ok("override replaces mapping")
    except Exception as e:
        report.fail("override replaces mapping", str(e))

    # ── Mailbox ───────────────────────────────────
    print("\n[Mailbox]")
    try:
        mb = Mailbox(_tmp_dir())
        msg = build_text_message(from_="lead", to="worker-1", summary="hi", content="hello")
        asyncio.run(mb.write("worker-1", msg))
        msgs = asyncio.run(mb.read("worker-1"))
        assert len(msgs) == 1 and msgs[0].content == "hello"
        report.ok("write/read basic")
    except Exception as e:
        report.fail("mailbox write/read", str(e))

    try:
        mb = Mailbox(_tmp_dir())
        assert asyncio.run(mb.read("nobody")) == []
        report.ok("empty read returns empty list")
    except Exception as e:
        report.fail("empty read", str(e))

    try:
        mb = Mailbox(_tmp_dir())
        asyncio.run(mb.write("worker", build_shutdown_request(from_="lead", to="worker", reason="wrap up")))
        msgs = asyncio.run(mb.read("worker"))
        assert msgs[0].type == "shutdown_request"
        asyncio.run(mb.write("lead", build_shutdown_response(from_="worker", to="lead", approved=True)))
        msgs = asyncio.run(mb.read("lead"))
        assert msgs[0].type == "shutdown_response" and msgs[0].payload["approve"] is True
        report.ok("shutdown message types")
    except Exception as e:
        report.fail("shutdown messages", str(e))

    try:
        mb = Mailbox(_tmp_dir())
        asyncio.run(mb.write("worker", build_plan_approval(from_="lead", to="worker", approve=False, feedback="no")))
        msgs = asyncio.run(mb.read("worker"))
        assert msgs[0].type == "plan_approval_response"
        assert msgs[0].payload["approve"] is False
        report.ok("plan approval message")
    except Exception as e:
        report.fail("plan approval message", str(e))

    try:
        mb = Mailbox(_tmp_dir())
        targets = ["w1", "w2", "w3"]
        factory = lambda to: build_text_message(from_="lead", to=to, summary="ping", content=f"hi {to}")
        asyncio.run(mb.write_many(targets, factory))
        for t in targets:
            assert len(asyncio.run(mb.read(t))) == 1
        report.ok("broadcast via write_many")
    except Exception as e:
        report.fail("broadcast", str(e))

    try:
        mb_dir = _tmp_dir()
        mb = Mailbox(mb_dir)
        async def _writer(i: int):
            await mb.write("worker", build_text_message("lead", "worker", f"m{i}", f"v{i}"))
        async def _run():
            await asyncio.gather(*(_writer(i) for i in range(20)))
        asyncio.run(_run())
        msgs = asyncio.run(mb.read("worker"))
        assert len(msgs) == 20
        report.ok("concurrent writers (20 tasks)")
    except Exception as e:
        report.fail("concurrent writers", str(e))

    # ── TaskStore ─────────────────────────────────
    print("\n[TaskStore]")
    try:
        store = TaskStore(_tmp_dir())
        tid = asyncio.run(store.create("Feature X", "do it", "worker"))
        t = asyncio.run(store.get(tid))
        assert t is not None and t.title == "Feature X" and t.assignee == "worker"
        report.ok("create/get")
    except Exception as e:
        report.fail("task create/get", str(e))

    try:
        store = TaskStore(_tmp_dir())
        id1 = asyncio.run(store.create("A", assignee="a"))
        id2 = asyncio.run(store.create("B", assignee="b"))
        asyncio.run(store.update(id1, status="completed"))
        pending = asyncio.run(store.list_(status="pending"))
        completed = asyncio.run(store.list_(status="completed"))
        assert len(pending) == 1 and pending[0].id == id2
        assert len(completed) == 1 and completed[0].id == id1
        report.ok("status filtering")
    except Exception as e:
        report.fail("status filtering", str(e))

    try:
        store = TaskStore(_tmp_dir())
        tid = asyncio.run(store.create("Old"))
        asyncio.run(store.update(tid, title="New"))
        assert asyncio.run(store.get(tid)).title == "New"
        report.ok("update title")
    except Exception as e:
        report.fail("update title", str(e))

    try:
        store = TaskStore(_tmp_dir())
        prereq = asyncio.run(store.create("Prereq", status="pending"))
        dep = asyncio.run(store.create("Dep", blocked_by=[prereq]))
        tasks = asyncio.run(store.list_())
        by_id = {t.id: t for t in tasks}
        assert prereq in by_id[dep].blocked_by
        assert dep in by_id[prereq].blocks
        report.ok("dependency wiring")
    except Exception as e:
        report.fail("dependency wiring", str(e))

    try:
        store = TaskStore(_tmp_dir())
        tid = asyncio.run(store.create("Delete me"))
        assert asyncio.run(store.get(tid)) is not None
        assert asyncio.run(store.delete(tid)) is True
        assert asyncio.run(store.get(tid)) is None
        report.ok("delete task")
    except Exception as e:
        report.fail("delete task", str(e))

    try:
        store_dir = _tmp_dir()
        store = TaskStore(store_dir)
        async def _creator(i: int):
            await store.create(f"t-{i}", f"d-{i}")
        async def _run():
            await asyncio.gather(*(_creator(i) for i in range(10)))
        asyncio.run(_run())
        assert len(asyncio.run(store.list_())) == 10
        report.ok("concurrent task creation (10 tasks)")
    except Exception as e:
        report.fail("concurrent task creation", str(e))

    # ── Tools ─────────────────────────────────────
    print("\n[Team Tools]")
    try:
        assert {"TeamCreate", "TeamDelete", "TaskCreate", "TaskGet",
                "TaskList", "TaskUpdate", "SendMessage"} == set(TEAM_TOOL_NAMES)
        assert is_team_tool("TeamCreate") is True
        assert is_team_tool("Agent") is False
        report.ok("TEAM_TOOL_NAMES constant + helper")
    except Exception as e:
        report.fail("TEAM_TOOL_NAMES", str(e))

    try:
        tm = TeamManager(_tmp_dir())
        reg = AgentNameRegistry()
        tools = build_team_tools(tm, registry=reg)
        assert len(tools) == 7
        report.ok("build_team_tools returns 7 tools")
    except Exception as e:
        report.fail("build_team_tools", str(e))

    try:
        from mewcode.team.tools.team_create import TeamCreateTool
        tm = TeamManager(_tmp_dir())
        tool = TeamCreateTool(tm)
        result = asyncio.run(tool.execute({"name": "Apollo", "description": "moon"}))
        assert not result.is_error
        assert "Apollo" in result.output
        report.ok("TeamCreate tool success")
    except Exception as e:
        report.fail("TeamCreate tool", str(e))

    try:
        from mewcode.team.tools.team_delete import TeamDeleteTool
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        tool = TeamDeleteTool(tm)
        result = asyncio.run(tool.execute({"name": "apollo"}))
        assert "deleted" in result.output.lower()
        report.ok("TeamDelete tool success")
    except Exception as e:
        report.fail("TeamDelete tool", str(e))

    try:
        from mewcode.team.tools.task_create import TaskCreateTool
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        tool = TaskCreateTool(tm)
        result = asyncio.run(tool.execute({
            "team": "apollo", "title": "Build it", "description": "now", "assignee": "eng"
        }))
        assert not result.is_error
        report.ok("TaskCreate tool success")
    except Exception as e:
        report.fail("TaskCreate tool", str(e))

    try:
        from mewcode.team.tools.task_create import TaskCreateTool
        from mewcode.team.tools.task_get import TaskGetTool
        from mewcode.team.tools.task_list import TaskListTool
        from mewcode.team.tools.task_update import TaskUpdateTool
        from mewcode.team.tools.send_message import SendMessageTool

        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        reg = AgentNameRegistry()

        TaskCreateTool(tm)
        TaskGetTool(tm)
        TaskListTool(tm)
        TaskUpdateTool(tm)
        SendMessageTool(tm, registry=reg, current_member="lead")
        report.ok("all 4 task tools + SendMessage instantiate")
    except Exception as e:
        report.fail("tools instantiation", str(e))

    try:
        from mewcode.team.tools.task_create import TaskCreateTool
        from mewcode.team.tools.task_update import TaskUpdateTool
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        create = TaskCreateTool(tm)
        asyncio.run(create.execute({"team": "apollo", "title": "T"}))
        team = asyncio.run(tm.get("apollo"))
        tasks = asyncio.run(TaskStore(team.config_dir).list_())
        tid = tasks[0].id
        upd = TaskUpdateTool(tm)
        r = asyncio.run(upd.execute({"team": "apollo", "task_id": tid, "status": "completed"}))
        assert "updated" in r.output.lower()
        report.ok("TaskUpdate tool success")
    except Exception as e:
        report.fail("TaskUpdate tool", str(e))

    try:
        from mewcode.team.tools.send_message import SendMessageTool
        tm = TeamManager(_tmp_dir())
        asyncio.run(tm.create("Apollo"))
        reg = AgentNameRegistry()
        tool = SendMessageTool(tm, registry=reg, current_member="lead")
        result = asyncio.run(tool.execute({
            "team": "apollo", "to": "worker-1", "summary": "ping", "message": "hello"
        }))
        assert "delivered" in result.output.lower()
        report.ok("SendMessage tool success")
    except Exception as e:
        report.fail("SendMessage tool", str(e))

    # ── InProcessBackend ──────────────────────────
    print("\n[InProcessBackend]")
    try:
        backend = InProcessBackend()
        assert backend.host_member_name() is None
        backend.mark_host_as("worker-1")
        assert backend.host_member_name() == "worker-1"
        assert backend.is_teammate_process() is True
        report.ok("host member tracking")
    except Exception as e:
        report.fail("host member tracking", str(e))

    try:
        backend = InProcessBackend()
        backend.mark_host_as("worker-1")
        req = SpawnRequest(team_name="test", member_name="sub", agent_id="sub-1")
        req.runnable = lambda *a, **kw: asyncio.sleep(0)
        got_error = False
        try:
            asyncio.run(backend.spawn(req))
        except Exception:
            got_error = True
        assert got_error, "should have rejected spawn from teammate"
        report.ok("teammate cannot spawn in-process")
    except Exception as e:
        report.fail("teammate spawn rejection", str(e))

    try:
        backend = InProcessBackend()
        ran: list[str] = []

        async def _r(req: SpawnRequest):
            ran.append(req.member_name)

        req = SpawnRequest(team_name="t", member_name="w1", agent_id="a1", runnable=_r)
        pane_id, aid = asyncio.run(backend.spawn(req))
        assert aid == "a1"
        assert pane_id.startswith("inproc:")
        report.ok("lead spawn succeeds")
    except Exception as e:
        report.fail("lead spawn", str(e))

    try:
        backend = InProcessBackend()
        assert asyncio.run(backend.wake("p1", "a1")) is False
        assert asyncio.run(backend.kill("a1")) is False
        report.ok("wake/kill safe on missing tasks")
    except Exception as e:
        report.fail("wake/kill safety", str(e))

    # ── Coordinator ───────────────────────────────
    print("\n[Coordinator]")
    old_env = os.environ.pop("MEWCODE_COORDINATOR_MODE", None)
    try:
        from mewcode.coordinator import is_enabled
        assert is_enabled() is False
        os.environ["MEWCODE_COORDINATOR_MODE"] = "1"
        assert is_enabled() is True
        report.ok("is_enabled env var gating")
    except Exception as e:
        report.fail("is_enabled", str(e))
    finally:
        if old_env is not None:
            os.environ["MEWCODE_COORDINATOR_MODE"] = old_env
        else:
            os.environ.pop("MEWCODE_COORDINATOR_MODE", None)

    try:
        from mewcode.coordinator import filter_tool_names
        allowed = filter_tool_names(["Agent", "read_file", "bash", "glob", "grep"])
        assert "Agent" in allowed and "read_file" in allowed
        # Block write tools
        blocked = filter_tool_names(["edit_file", "write_file", "write_file_tool", "read_file"])
        assert "edit_file" not in blocked
        assert "write_file" not in blocked
        assert "write_file_tool" not in blocked
        assert "read_file" in blocked
        # Team tools should be allowed
        team_result = filter_tool_names(list(TEAM_TOOL_NAMES))
        for tn in TEAM_TOOL_NAMES:
            assert tn in team_result
        report.ok("filter_tool_names whitelist + blacklist")
    except Exception as e:
        report.fail("filter_tool_names", str(e))

    try:
        from mewcode.coordinator import system_prompt_suffix
        text = system_prompt_suffix()
        assert len(text) > 0 and "coordinator" in text.lower()
        report.ok("system_prompt_suffix non-empty")
    except Exception as e:
        report.fail("system_prompt_suffix", str(e))

    # ── End-to-end ────────────────────────────────
    print("\n[End-to-end]")
    try:
        tm = TeamManager(_tmp_dir())
        reg = AgentNameRegistry()
        # 1
        team = asyncio.run(tm.create("Alpha", description="test"))
        assert team.sanitized_name == "alpha"
        # 2
        reg.register("worker", "agent-1")
        # 3
        asyncio.run(tm.add_member("alpha", TeammateInfo(
            name="worker", agent_id="agent-1", agent_type="coder",
            backend_type=BackendType.IN_PROCESS, is_active=True,
        )))
        # 4
        team = asyncio.run(tm.get("alpha"))
        store = TaskStore(team.config_dir)
        tid = asyncio.run(store.create("Login", "Auth flow", "worker"))
        # 5
        asyncio.run(store.update(tid, status="in_progress"))
        t = asyncio.run(store.get(tid))
        assert t.status == "in_progress"
        # 6
        mb = Mailbox(team.mailbox_dir)
        asyncio.run(mb.write("worker", build_text_message("lead", "worker", "ping", "how's it going")))
        msgs = asyncio.run(mb.read("worker"))
        assert len(msgs) == 1 and msgs[0].content == "how's it going"
        report.ok("full team workflow (create → member → task → message)")
    except Exception as e:
        report.fail("full team workflow", str(e))

    # ── Summary ───────────────────────────────────
    print()
    total = report.passed + report.failed
    print("=" * 50)
    print(f"Results: {report.passed}/{total} passed")
    if report.errors:
        print(f"\nFailures ({len(report.errors)}):")
        for name, err in report.errors:
            print(f"  - {name}: {err[:200]}")
    print("=" * 50)
    return report


if __name__ == "__main__":
    r = run_all()
    sys.exit(0 if r.failed == 0 else 1)