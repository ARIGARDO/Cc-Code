"""Tests for MCP integration (ch07)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mewcode.config import (
    ConfigError,
    MCPServerConfig,
    build_child_env,
    load_config,
    resolve_env_vars,
)
from mewcode.mcp.client import MCPClient
from mewcode.mcp.manager import MCPManager
from mewcode.mcp.tool_wrapper import MCPToolWrapper, _build_params_model, _extract_text
from mewcode.tools import ToolRegistry
from mewcode.tools.base import ToolResult


# ──────────────────────────────────────────────
#  TestResolveEnvVars
# ──────────────────────────────────────────────

class TestResolveEnvVars:
    def test_expands_existing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "abc123")
        assert resolve_env_vars("Bearer ${MY_TOKEN}") == "Bearer abc123"

    def test_missing_var_kept_as_is(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOPE_NOT_HERE", raising=False)
        assert resolve_env_vars("${NOPE_NOT_HERE}") == "${NOPE_NOT_HERE}"

    def test_no_vars_unchanged(self) -> None:
        assert resolve_env_vars("plain text") == "plain text"

    def test_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert resolve_env_vars("${A}-${B}") == "1-2"


# ──────────────────────────────────────────────
#  TestBuildChildEnv
# ──────────────────────────────────────────────

class TestBuildChildEnv:
    def test_excludes_host_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        monkeypatch.setenv("PATH", "/usr/bin")
        env = build_child_env()
        assert "ANTHROPIC_API_KEY" not in env
        assert env.get("PATH") == "/usr/bin"

    def test_includes_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_VAR", "val")
        env = build_child_env({"MY_VAR": "${MY_VAR}"})
        assert env["MY_VAR"] == "val"

    def test_extra_overrides_whitelist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        env = build_child_env({"PATH": "/custom"})
        assert env["PATH"] == "/custom"


# ──────────────────────────────────────────────
#  TestLoadConfigMCP
# ──────────────────────────────────────────────

class TestLoadConfigMCP:
    def test_stdio_server(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "mcp_servers:\n"
            "  - name: ctx7\n"
            "    command: npx\n"
            "    args: ['-y', '@upstash/context7-mcp']\n"
        )
        cfg = load_config(cfg_file)
        assert len(cfg.mcp_servers) == 1
        srv = cfg.mcp_servers[0]
        assert srv.name == "ctx7"
        assert srv.command == "npx"
        assert srv.args == ["-y", "@upstash/context7-mcp"]
        assert srv.is_stdio is True

    def test_http_server(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "mcp_servers:\n"
            "  - name: remote\n"
            "    url: http://localhost:8080/mcp\n"
            "    headers:\n"
            "      Authorization: 'Bearer ${TOKEN}'\n"
        )
        cfg = load_config(cfg_file)
        srv = cfg.mcp_servers[0]
        assert srv.url == "http://localhost:8080/mcp"
        assert srv.is_stdio is False
        assert srv.headers["Authorization"] == "Bearer ${TOKEN}"

    def test_both_command_and_url_errors(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "mcp_servers:\n"
            "  - name: bad\n"
            "    command: npx\n"
            "    url: http://x\n"
        )
        with pytest.raises(ConfigError, match="cannot have both"):
            load_config(cfg_file)

    def test_neither_command_nor_url_errors(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "mcp_servers:\n"
            "  - name: bad\n"
        )
        with pytest.raises(ConfigError, match="must have either"):
            load_config(cfg_file)

    def test_dict_format(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "mcp_servers:\n"
            "  ctx7:\n"
            "    command: npx\n"
            "    args: ['-y', 'x']\n"
        )
        cfg = load_config(cfg_file)
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0].name == "ctx7"

    def test_no_mcp_servers(self, tmp_path: Any) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("providers: []\n")
        cfg = load_config(cfg_file)
        assert cfg.mcp_servers == []


# ──────────────────────────────────────────────
#  TestMCPToolWrapper
# ──────────────────────────────────────────────

class TestMCPToolWrapper:
    def test_name_format(self) -> None:
        tool_def = MagicMock()
        tool_def.name = "resolve_library_id"
        tool_def.description = "Resolve a library"
        tool_def.inputSchema = {"type": "object", "properties": {}}
        client = MagicMock()
        client.is_alive = True
        wrapper = MCPToolWrapper("context7", tool_def, client)
        assert wrapper.name == "mcp_context7_resolve_library_id"

    def test_get_schema_returns_original(self) -> None:
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        tool_def = MagicMock()
        tool_def.name = "search"
        tool_def.description = "Search"
        tool_def.inputSchema = schema
        client = MagicMock()
        client.is_alive = True
        wrapper = MCPToolWrapper("srv", tool_def, client)
        assert wrapper.get_schema() is schema

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        tool_def = MagicMock()
        tool_def.name = "echo"
        tool_def.description = "Echo"
        tool_def.inputSchema = {"type": "object", "properties": {}}

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "hello"

        result = MagicMock()
        result.content = [text_block]
        result.isError = False

        client = MagicMock()
        client.is_alive = True
        client.call_tool = AsyncMock(return_value=result)

        wrapper = MCPToolWrapper("srv", tool_def, client)
        res = await wrapper.execute({})
        assert isinstance(res, ToolResult)
        assert res.output == "hello"
        assert res.is_error is False

    @pytest.mark.asyncio
    async def test_execute_error_propagates_isError(self) -> None:
        tool_def = MagicMock()
        tool_def.name = "fail"
        tool_def.description = "Fail"
        tool_def.inputSchema = {"type": "object", "properties": {}}

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "boom"

        result = MagicMock()
        result.content = [text_block]
        result.isError = True

        client = MagicMock()
        client.is_alive = True
        client.call_tool = AsyncMock(return_value=result)

        wrapper = MCPToolWrapper("srv", tool_def, client)
        res = await wrapper.execute({})
        assert res.is_error is True
        assert res.output == "boom"

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self) -> None:
        tool_def = MagicMock()
        tool_def.name = "crash"
        tool_def.description = "Crash"
        tool_def.inputSchema = {"type": "object", "properties": {}}

        client = MagicMock()
        client.is_alive = True
        client.call_tool = AsyncMock(side_effect=RuntimeError("disconnected"))

        wrapper = MCPToolWrapper("srv", tool_def, client)
        res = await wrapper.execute({})
        assert res.is_error is True
        assert "disconnected" in res.output


# ──────────────────────────────────────────────
#  TestExtractText
# ──────────────────────────────────────────────

class TestExtractText:
    def test_text_content(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "hi"
        assert _extract_text([block]) == "hi"

    def test_image_content(self) -> None:
        block = MagicMock()
        block.type = "image"
        block.mimeType = "image/png"
        assert _extract_text([block]) == "[image: image/png]"

    def test_embedded_resource_text(self) -> None:
        block = MagicMock()
        block.type = "resource"
        block.resource = MagicMock()
        block.resource.text = "resource body"
        assert _extract_text([block]) == "resource body"

    def test_embedded_resource_uri(self) -> None:
        block = MagicMock()
        block.type = "resource"
        block.resource = MagicMock()
        block.resource.text = None
        block.resource.uri = "file:///x"
        assert _extract_text([block]) == "[resource: file:///x]"

    def test_empty_returns_no_output(self) -> None:
        assert _extract_text([]) == "(no output)"

    def test_multiple_blocks(self) -> None:
        b1 = MagicMock()
        b1.type = "text"
        b1.text = "a"
        b2 = MagicMock()
        b2.type = "text"
        b2.text = "b"
        assert _extract_text([b1, b2]) == "a\nb"


# ──────────────────────────────────────────────
#  TestBuildParamsModel
# ──────────────────────────────────────────────

class TestBuildParamsModel:
    def test_required_field(self) -> None:
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "query"}},
            "required": ["q"],
        }
        model = _build_params_model("search", schema)
        fields = model.model_fields
        assert "q" in fields

    def test_optional_field(self) -> None:
        schema = {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        }
        model = _build_params_model("search", schema)
        fields = model.model_fields
        assert "limit" in fields

    def test_type_mapping(self) -> None:
        from mewcode.mcp.tool_wrapper import _json_type_to_python
        assert _json_type_to_python("string") is str
        assert _json_type_to_python("integer") is int
        assert _json_type_to_python("number") is float
        assert _json_type_to_python("boolean") is bool
        assert _json_type_to_python("object") is dict
        assert _json_type_to_python("array") is list


# ──────────────────────────────────────────────
#  TestMCPManagerPartialFailure
# ──────────────────────────────────────────────

class TestMCPManagerPartialFailure:
    @pytest.mark.asyncio
    async def test_single_server_failure_does_not_block_others(self) -> None:
        good_cfg = MCPServerConfig(name="good", command="echo")
        bad_cfg = MCPServerConfig(name="bad", command="false")

        manager = MCPManager()
        manager.load_configs([good_cfg, bad_cfg])
        registry = ToolRegistry()

        # Patch MCPClient.connect to fail for "bad" and succeed for "good"
        async def fake_connect(self: MCPClient) -> None:
            if self.name == "bad":
                raise RuntimeError("connection refused")
            # Simulate a successful connect + empty tool list
            self._alive = True
            self._session = MagicMock()

        async def fake_list_tools(self: MCPClient) -> list:
            return []

        with patch.object(MCPClient, "connect", fake_connect), \
             patch.object(MCPClient, "list_tools", fake_list_tools):
            errors = await manager.register_all_tools(registry)

        assert len(errors) == 1
        assert "bad" in errors[0]
        # Good server still connected
        assert manager.get_client("good") is not None
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        manager = MCPManager()
        await manager.shutdown()  # no clients — should not raise
        await manager.shutdown()  # again — still fine

    @pytest.mark.asyncio
    async def test_get_client_lazy_connect(self) -> None:
        cfg = MCPServerConfig(name="srv", command="echo")
        manager = MCPManager()
        manager.load_configs([cfg])
        # No client yet
        assert manager.get_client("srv") is not None  # creates one
        assert manager.get_client("nonexistent") is None