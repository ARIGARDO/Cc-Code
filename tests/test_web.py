"""Browser transport integration with a deterministic Agent."""
import asyncio
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from cccode.agent import LoopComplete, PermissionRequest, PermissionResponse, StreamText, ToolResultEvent, ToolUseEvent
from cccode.web import server


class FakeAgent:
    async def run(self, conversation):
        yield StreamText("开始")
        yield ToolUseEvent("tool-1", "WriteFile", {"path": "demo.txt"})
        future = asyncio.get_running_loop().create_future()
        yield PermissionRequest("WriteFile", {"path": "demo.txt"}, future)
        decision = await future
        yield ToolResultEvent("tool-1", "WriteFile", decision.value, decision == PermissionResponse.DENY)
        yield StreamText("完成")
        yield LoopComplete("end_turn")


@pytest.mark.asyncio
async def test_browser_conversation_tool_permission(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    async def start(runtime):
        runtime.agent = FakeAgent()
        await runtime.send("ready", model="test", cwd=str(tmp_path), mode="default")

    monkeypatch.setattr(server.BrowserRuntime, "start", start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        page = await client.get("/")
        assert page.status == 200
        assert "CcCode" in await page.text()
        forbidden = await client.get("/ws", headers={"Origin": "http://evil.example"})
        assert forbidden.status == 403
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        assert (await ws.receive_json())["type"] == "ready"
        await ws.send_json({"type": "message", "text": "测试"})
        events = []
        while True:
            message = await asyncio.wait_for(ws.receive_json(), timeout=3)
            events.append(message)
            if message["type"] == "permission":
                await ws.send_json({"type": "permission", "value": "allow"})
            if message["type"] == "busy" and not message["busy"]:
                break
        assert [m["event"] for m in events if m["type"] == "agent_event"] == ["StreamText", "ToolUseEvent", "ToolResultEvent", "StreamText", "LoopComplete"]
        result = next(m for m in events if m.get("event") == "ToolResultEvent")
        assert result["data"]["result"] == "allow"
        await ws.close()


@pytest.mark.asyncio
async def test_stop_cancels_pending_permission(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cancelled = asyncio.Event()

    class WaitingAgent:
        async def run(self, conversation):
            try:
                future = asyncio.get_running_loop().create_future()
                yield PermissionRequest("Bash", {"command": "echo test"}, future)
                await future
            finally:
                cancelled.set()

    async def start(runtime):
        runtime.agent = WaitingAgent()
        await runtime.send("ready", model="test", cwd=str(tmp_path), mode="default")

    monkeypatch.setattr(server.BrowserRuntime, "start", start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        await ws.receive_json()
        await ws.send_json({"type": "message", "text": "测试"})
        while (await asyncio.wait_for(ws.receive_json(), 3))["type"] != "permission":
            pass
        await ws.send_json({"type": "stop"})
        await asyncio.wait_for(cancelled.wait(), 3)
        await ws.close()


@pytest.mark.asyncio
async def test_real_runtime_initializes_without_terminal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("cccode.app.create_client", lambda config: object())
    (tmp_path / "config.yaml").write_text("providers:\n  - protocol: openai\n    model: test-model\n    api_key: test\n", encoding="utf-8")
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        message = await asyncio.wait_for(ws.receive_json(), 3)
        assert message["type"] == "ready", message
        assert message["model"] == "test-model"
        await ws.close()


@pytest.mark.asyncio
async def test_stream_events_arrive_before_agent_finishes(monkeypatch, tmp_path):
    from cccode.agent import ThinkingText
    monkeypatch.chdir(tmp_path)
    release = asyncio.Event()

    class StreamingAgent:
        async def run(self, conversation):
            yield ThinkingText("思考中")
            yield StreamText("第一段")
            await release.wait()
            yield StreamText("第二段")
            yield LoopComplete("end_turn")

    async def start(runtime):
        runtime.agent = StreamingAgent()
        await runtime.send("ready", model="test", cwd=str(tmp_path), mode="default")

    monkeypatch.setattr(server.BrowserRuntime, "start", start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        await ws.receive_json()
        await ws.send_json({"type": "message", "text": "测试"})
        first = []
        while len(first) < 2:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            if event["type"] == "agent_event":
                first.append(event)
        assert [e["event"] for e in first] == ["ThinkingText", "StreamText"]
        assert first[1]["data"]["text"] == "第一段"
        release.set()
        while True:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            if event.get("event") == "StreamText":
                assert event["data"]["text"] == "第二段"
                break
        await ws.close()


@pytest.mark.asyncio
async def test_invalid_config_reports_error_without_exposing_contents(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("providers: [\n  secret-value: [", encoding="utf-8")
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        message = await asyncio.wait_for(ws.receive_json(), 3)
        assert message["type"] == "error"
        assert "配置加载失败" in message["message"]
        assert "secret-value" not in message["message"]
        await ws.close()


@pytest.mark.asyncio
async def test_session_history_resume_uses_existing_session_store(tmp_path):
    from cccode.conversation import Message
    from cccode.memory import SessionManager

    class Socket:
        closed = False
        def __init__(self): self.events = []
        async def send_json(self, data): self.events.append(data)

    socket = Socket()
    runtime = server.BrowserRuntime(socket, {})
    runtime.session_manager = SessionManager(tmp_path)
    original = runtime.session_manager.create()
    original.append(Message(role="user", content="第一段对话"))
    original.append(Message(role="assistant", content="第一段回答"))
    original_id = original.session_id
    original.close()
    runtime.session = runtime.session_manager.create()
    await runtime.send_sessions()
    assert original_id in [s["id"] for s in socket.events[-1]["sessions"]]
    await runtime.resume_session(original_id)
    restored = next(event for event in socket.events if event["type"] == "restore")
    assert [message["text"] for message in restored["messages"]] == ["第一段对话", "第一段回答"]
    assert runtime.session.session_id == original_id
    await runtime.close()


@pytest.mark.asyncio
async def test_session_history_through_websocket(monkeypatch, tmp_path):
    from cccode.memory import SessionManager
    monkeypatch.chdir(tmp_path)

    class SessionAgent:
        async def run(self, conversation):
            conversation.add_assistant_message(content="已收到")
            yield StreamText("已收到")
            yield LoopComplete("end_turn")
        def clear_active_skills(self):
            pass

    async def start(runtime):
        runtime.agent = SessionAgent()
        runtime.session_manager = SessionManager(tmp_path)
        runtime.session = runtime.session_manager.create()
        await runtime.send("ready", model="test", cwd=str(tmp_path), mode="default")
        await runtime.send_sessions()

    monkeypatch.setattr(server.BrowserRuntime, "start", start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url("/")).rstrip("/")
        ws = await client.ws_connect("/ws", headers={"Origin": origin})
        assert (await ws.receive_json())["type"] == "ready"
        original = (await ws.receive_json())["current"]
        await ws.send_json({"type": "message", "text": "原会话"})
        while True:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            if event["type"] == "busy" and not event["busy"]:
                break
        await ws.send_json({"type": "message", "text": "/new"})
        while True:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            if event["type"] == "sessions":
                assert any(s["id"] == original and s["title"] == "原会话" for s in event["sessions"])
            if event["type"] == "busy" and not event["busy"]:
                break
        await ws.send_json({"type": "resume", "session_id": original})
        restored = await asyncio.wait_for(ws.receive_json(), 3)
        assert restored["type"] == "restore"
        assert [m["text"] for m in restored["messages"]] == ["原会话", "已收到"]
        await ws.close()


def test_session_round_trips_thinking_and_tools(tmp_path):
    from cccode.conversation import Message, ThinkingBlock, ToolUseBlock, ToolResultBlock
    from cccode.memory import SessionManager

    manager = SessionManager(tmp_path)
    session = manager.create()
    session.append(Message(role='user', content='问题'))
    session.append(Message(role='assistant', content='回答', thinking_blocks=[ThinkingBlock('分析', '签名')], tool_uses=[ToolUseBlock('id', 'Bash', {'command': 'pwd'})]))
    session.append(Message(role='user', tool_results=[ToolResultBlock('id', '/tmp')]))
    session_id = session.session_id
    session.close()
    restored = manager.resume(session_id)
    assert restored.messages[1].thinking_blocks[0] == ThinkingBlock('分析', '签名')
    display = server.BrowserRuntime.restore_messages(restored.messages)
    assert display[1]['thinking'] == ['分析']
    assert display[1]['tool_uses'][0]['name'] == 'Bash'
    assert display[2]['tool_results'][0]['content'] == '/tmp'
    restored.session.close()


@pytest.mark.asyncio
async def test_workspace_switch_reinitializes_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr('cccode.app.create_client', lambda config: object())
    (tmp_path / 'config.yaml').write_text('providers:\n  - protocol: openai\n    model: test-model\n    api_key: test\n')
    project = tmp_path / 'another'
    project.mkdir()
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin': origin})
        assert (await ws.receive_json())['type'] == 'ready'
        await ws.receive_json()
        await ws.send_json({'type': 'workspace', 'path': str(project)})
        ready = await asyncio.wait_for(ws.receive_json(), 3)
        assert ready['type'] == 'ready' and ready['cwd'] == str(project)
        assert (await ws.receive_json())['type'] == 'sessions'
        assert (await ws.receive_json())['type'] == 'clear'
        await ws.send_json({'type': 'workspace', 'path': str(project / 'missing')})
        assert (await ws.receive_json())['type'] == 'error'
        await ws.close()

@pytest.mark.asyncio
async def test_browser_skill_completion(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr('cccode.app.create_client', lambda config: object())
    (tmp_path / 'config.yaml').write_text('providers:\n  - protocol: openai\n    model: test-model\n    api_key: test\n')
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin': origin})
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json({'type': 'complete', 'text': '/skill'})
        result = await asyncio.wait_for(ws.receive_json(), 3)
        assert result['type'] == 'completions'
        values = [item['value'] for item in result['entries']]
        assert '/skill' in values and '/review' in values
        await ws.send_json({'type': 'complete', 'text': '/sk'})
        result = await asyncio.wait_for(ws.receive_json(), 3)
        skills = [item for item in result['entries'] if item['group'] == 'skill']
        assert any(item['value'] == '/review' and item['source'] == 'builtin' and item['description'] for item in skills)
        assert any(item['value'] == '/skill' and item['group'] == 'command' for item in result['entries'])
        await ws.send_json({'type': 'complete', 'text': '/rev'})
        result = await asyncio.wait_for(ws.receive_json(), 3)
        assert [item['value'] for item in result['entries'] if item['group'] == 'skill'] == ['/review']
        await ws.send_json({'type': 'message', 'text': '/skill'})
        events = []
        while True:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            events.append(event)
            if event['type'] == 'busy' and not event['busy']:
                break
        # Notices are scheduled by the existing command UI controller.
        if not any(e['type'] == 'notice' and 'review' in e['text'] for e in events):
            assert 'review' in (await asyncio.wait_for(ws.receive_json(), 3))['text']
        await ws.close()

@pytest.mark.asyncio
async def test_workspace_switch_keeps_websocket_with_mcp(monkeypatch, tmp_path):
    import json
    import sys
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr('cccode.app.create_client', lambda config: object())
    connected_projects = []
    original_init = server.BrowserRuntime._init_mcp
    async def checked_init(runtime):
        await original_init(runtime)
        assert runtime.registry.get('mcp_test_ping') is not None
        connected_projects.append(runtime._work_dir)
    monkeypatch.setattr(server.BrowserRuntime, '_init_mcp', checked_init)
    mcp_script = tmp_path / 'server.py'
    mcp_script.write_text('from mcp.server.fastmcp import FastMCP\nm = FastMCP("test")\n@m.tool()\ndef ping() -> str:\n    return "pong"\nm.run()\n')
    (tmp_path / 'config.yaml').write_text(json.dumps({'providers': [{'protocol': 'openai', 'model': 'test-model', 'api_key': 'test'}], 'mcp_servers': [{'name': 'test', 'command': sys.executable, 'args': [str(mcp_script)]}]}))
    project = tmp_path / 'project'
    project.mkdir()
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin': origin})
        assert (await asyncio.wait_for(ws.receive_json(), 10))['type'] == 'ready'
        await ws.receive_json()
        for path in (project, tmp_path):
            await ws.send_json({'type': 'workspace', 'path': str(path)})
            ready = await asyncio.wait_for(ws.receive_json(), 10)
            assert ready['type'] == 'ready' and ready['cwd'] == str(path)
            assert (await ws.receive_json())['type'] == 'sessions'
            assert (await ws.receive_json())['type'] == 'clear'
            await ws.send_json({'type': 'complete', 'text': '/sk'})
            assert (await asyncio.wait_for(ws.receive_json(), 5))['type'] == 'completions'
        assert connected_projects == [tmp_path, project, tmp_path]
        await ws.close()


@pytest.mark.asyncio
async def test_failed_model_request_preserves_completed_tool_history(tmp_path):
    from cccode.conversation import ToolUseBlock, ToolResultBlock
    from cccode.memory import SessionManager
    from cccode.client import NetworkError

    class Socket:
        closed = False
        def __init__(self): self.events = []
        async def send_json(self, data): self.events.append(data)
    class Agent:
        async def run(self, conversation):
            conversation.add_assistant_message(tool_uses=[ToolUseBlock('id', 'ReadFile', {'file_path':'a'})])
            conversation.add_tool_results_message([ToolResultBlock('id', 'result')])
            yield ToolResultEvent('id', 'ReadFile', 'result', False)
            raise NetworkError('模型服务连接或响应超时')

    ws = Socket()
    runtime = server.BrowserRuntime(ws, {})
    runtime.agent = Agent()
    runtime.session_manager = SessionManager(tmp_path)
    runtime.session = runtime.session_manager.create()
    session_id = runtime.session.session_id
    await runtime.process('hello')
    assert any(e['type'] == 'error' and '超时' in e['message'] for e in ws.events)
    runtime.session.close()
    restored = runtime.session_manager.resume(session_id)
    assert restored.messages[1].tool_uses[0].id == 'id'
    assert restored.messages[2].tool_results[0].content == 'result'
    restored.session.close()


@pytest.mark.asyncio
async def test_delete_sessions_keeps_other_history_and_resets_current(tmp_path):
    from cccode.conversation import Message
    from cccode.memory import SessionManager

    class Socket:
        closed = False
        def __init__(self): self.events = []
        async def send_json(self, data): self.events.append(data)
    class Agent:
        def clear_active_skills(self): pass

    socket = Socket()
    runtime = server.BrowserRuntime(socket, {})
    runtime.agent = Agent()
    runtime.session_manager = SessionManager(tmp_path)
    older = runtime.session_manager.create()
    older.append(Message(role='user', content='保留的会话'))
    older_id = older.session_id
    older.close()
    runtime.session = runtime.session_manager.create()
    current_id = runtime.session.session_id
    runtime.session.append(Message(role='user', content='当前会话'))
    runtime.conversation.add_user_message('当前会话')
    await runtime.delete_session('../../outside')
    assert socket.events[-1]['type'] == 'error'
    await runtime.delete_session(current_id)
    assert runtime.session.session_id != current_id
    assert runtime.conversation.history == []
    assert any(event['type'] == 'clear' for event in socket.events)
    assert runtime.session_manager.resume(current_id) is None
    resumed = runtime.session_manager.resume(older_id)
    assert resumed is not None and resumed.messages[0].content == '保留的会话'
    resumed.session.close()
    new_current = runtime.session.session_id
    await runtime.delete_session(older_id)
    assert runtime.session.session_id == new_current
    assert runtime.session_manager.resume(older_id) is None
    await runtime.close()


def test_web_permission_menu_has_three_modes():
    from cccode.permissions.modes import PermissionMode, mode_decide
    html = (server.STATIC / 'index.html').read_text()
    import re
    assert re.findall(r'data-mode="([^"]+)"', html) == ['default', 'plan', 'bypassPermissions']
    assert mode_decide(PermissionMode.DEFAULT, 'write') == 'ask'
    assert mode_decide(PermissionMode.PLAN, 'write') == 'deny'
    assert mode_decide(PermissionMode.BYPASS, 'write') == 'allow'


@pytest.mark.asyncio
async def test_delete_session_over_websocket_removes_files(monkeypatch, tmp_path):
    from cccode.conversation import Message
    from cccode.memory import SessionManager
    monkeypatch.chdir(tmp_path)

    class Agent:
        def clear_active_skills(self): pass

    async def start(runtime):
        runtime.agent = Agent()
        runtime.session_manager = SessionManager(tmp_path)
        runtime.session = runtime.session_manager.create()
        runtime.session.append(Message(role='user', content='待删除'))
        await runtime.send('ready', model='test', cwd=str(tmp_path), mode='default')
        await runtime.send_sessions()

    monkeypatch.setattr(server.BrowserRuntime, 'start', start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin': origin})
        await ws.receive_json()
        session_id = (await ws.receive_json())['current']
        session_dir = tmp_path / '.cccode' / 'sessions'
        assert (session_dir / f'{session_id}.jsonl').exists()
        assert (session_dir / f'{session_id}.meta').exists()
        await ws.send_json({'type': 'delete_session', 'session_id': session_id})
        assert (await ws.receive_json())['type'] == 'clear'
        listing = await ws.receive_json()
        assert listing['type'] == 'sessions' and listing['current'] != session_id
        assert all(item['id'] != session_id for item in listing['sessions'])
        assert (await ws.receive_json()) == {'type': 'session_deleted', 'session_id': session_id}
        assert not (session_dir / f'{session_id}.jsonl').exists()
        assert not (session_dir / f'{session_id}.meta').exists()
        await ws.close()


@pytest.mark.asyncio
async def test_plan_approval_switches_mode_and_continues_without_extra_message(monkeypatch, tmp_path):
    from cccode.permissions.modes import PermissionMode
    monkeypatch.chdir(tmp_path)
    runs = []

    class Agent:
        permission_mode = PermissionMode.PLAN
        def set_permission_mode(self, value): self.permission_mode = value
        async def run(self, conversation):
            runs.append((self.permission_mode, conversation.history[-1].content))
            yield StreamText('计划内容' if self.permission_mode == PermissionMode.PLAN else '继续执行')
            yield LoopComplete('end_turn')

    async def start(runtime):
        runtime.agent = Agent()
        await runtime.send('ready', model='test', cwd=str(tmp_path), mode='plan')

    monkeypatch.setattr(server.BrowserRuntime, 'start', start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin': origin})
        await ws.receive_json()
        await ws.send_json({'type':'message', 'text':'创建文件'})
        while (await asyncio.wait_for(ws.receive_json(), 3))['type'] != 'plan_review': pass
        assert runs == [(PermissionMode.PLAN, '创建文件')]
        await ws.send_json({'type':'plan_decision', 'value':'approve'})
        assert (await ws.receive_json()) == {'type':'status', 'mode':'default'}
        while True:
            msg = await asyncio.wait_for(ws.receive_json(), 3)
            if msg['type'] == 'busy' and not msg['busy']: break
        assert len(runs) == 2
        assert runs[1] == (PermissionMode.DEFAULT, '已批准计划，请继续执行之前的任务。')
        await ws.close()


@pytest.mark.asyncio
async def test_plan_stay_does_not_execute_or_change_mode(monkeypatch, tmp_path):
    from cccode.permissions.modes import PermissionMode
    monkeypatch.chdir(tmp_path)
    runs = []
    class Agent:
        permission_mode = PermissionMode.PLAN
        def set_permission_mode(self, value): self.permission_mode = value
        async def run(self, conversation):
            runs.append(self.permission_mode)
            yield StreamText('计划')
            yield LoopComplete('end_turn')
    async def start(runtime):
        runtime.agent = Agent()
        await runtime.send('ready', model='test', cwd=str(tmp_path), mode='plan')
    monkeypatch.setattr(server.BrowserRuntime, 'start', start)
    async with TestClient(TestServer(server.create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        ws = await client.ws_connect('/ws', headers={'Origin':origin})
        await ws.receive_json()
        await ws.send_json({'type':'message', 'text':'请规划'})
        while (await asyncio.wait_for(ws.receive_json(), 3))['type'] != 'plan_review': pass
        await ws.send_json({'type':'plan_decision', 'value':'stay'})
        await ws.send_json({'type':'plan_decision', 'value':'approve'})
        assert (await asyncio.wait_for(ws.receive_json(), 3))['type'] == 'error'
        assert (await ws.receive_json())['busy'] is False
        assert runs == [PermissionMode.PLAN]
        await ws.close()
