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
