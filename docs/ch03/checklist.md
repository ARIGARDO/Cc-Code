# ch03: 工具系统 Checklist

> 所有条目必须可勾选、可观测。验收方式写在每项后面的括号里。

## 1. 实现完整性

- [x] `Tool` ABC 在 `mewcode/tools/base.py:22-45` 定义 `name`/`description`/`params_model`/`category`/`is_concurrency_safe`/`is_system_tool`/`should_defer` 七个类属性以及 `is_read_only` property、`get_schema()` 方法、`@abstractmethod async def execute()`（`grep -n 'class Tool(ABC)' mewcode/tools/base.py`）。
- [x] `ToolResult` 在 `mewcode/tools/base.py:16-19` 以 `@dataclass` 定义 `output: str` + `is_error: bool = False`。
- [x] `ToolCategory = Literal["read", "write", "command"]` 在 `mewcode/tools/base.py:13`（`grep -n 'ToolCategory' mewcode/tools/base.py`）。
- [x] `SKIP_DIRS` 在 `mewcode/tools/base.py:9` 列出 `.git/.venv/node_modules/__pycache__/.tox/.mypy_cache` 六项（`grep -n 'SKIP_DIRS' mewcode/tools/base.py`）。
- [x] `MAX_OUTPUT_CHARS = 10000` 在 `mewcode/tools/base.py:11` 作为全局结果上限。
- [x] 流式事件 `TextDelta` / `ToolCallStart` / `ToolCallDelta` / `ToolCallComplete` / `ThinkingDelta` / `ThinkingComplete` / `StreamEnd` 与 `StreamEvent` Union 集中在 `mewcode/tools/base.py:50-92`（`grep -c '^@dataclass' mewcode/tools/base.py` ≥ 8）。
- [x] `ToolRegistry` 在 `mewcode/tools/__init__.py:11-123` 提供 `register` / `get` / `is_enabled` / `enable` / `disable` / `enable_all` / `mark_discovered` / `is_discovered` / `get_deferred_tool_names` / `search_deferred` / `find_deferred_by_names` / `list_tools` / `get_all_schemas` 共 13 个公开方法。
- [x] `get_all_schemas` 在 protocol == "openai" 时输出 `{type: "function", name, description, parameters}` 形状（`mewcode/tools/__init__.py:113-122`）。
- [x] `create_default_registry` 在 `mewcode/tools/__init__.py:126-144` 一次性注册 6 个核心工具（`grep -c 'registry.register' mewcode/tools/__init__.py` == 6）。
- [x] `ReadFile` 在 `mewcode/tools/read_file.py:20-51`，`name="ReadFile"`、`category="read"`、`is_concurrency_safe=True`、`offset` 默认 0、`limit` 默认 2000、行号 1-based `<line_no>\t<content>` 输出。
- [x] `WriteFile` 在 `mewcode/tools/write_file.py:19-37`，`category="write"`、写前 `path.parent.mkdir(parents=True, exist_ok=True)`、成功输出 `Successfully wrote to <path>`。
- [x] `EditFile` 在 `mewcode/tools/edit_file.py:20-56`，唯一性校验三分支 `count == 0 / 1 / N`，N>1 时报 `found N times, must be unique`。
- [x] `Bash` 在 `mewcode/tools/bash.py:17-49`，`MAX_TIMEOUT = 600`、`asyncio.create_subprocess_shell` + `asyncio.wait_for(timeout)`、输出含 `STDOUT:` / `STDERR:` 段、超时返回 `Error: command timed out after Ns`、`is_error = (returncode != 0)`。
- [x] `Glob` 在 `mewcode/tools/glob.py:15-38`，跳过 `SKIP_DIRS`、字典序输出相对路径、无匹配返回 `No files matched the pattern.`。
- [x] `Grep` 在 `mewcode/tools/grep.py:17-55`，`re.compile` + `include` glob + 跳过 `SKIP_DIRS` + `<rel>:<line_num>:<line>` 输出、无匹配返回 `No matches found.`。
- [x] `ToolSearchTool` 在 `mewcode/tools/impl/tool_search.py:19-83`，支持 `select:` 前缀与关键词两种查询；命中后逐个 `registry.mark_discovered`；未命中返回 `No matching deferred tools for "..."`。
- [x] `AskUserTool` 在 `mewcode/tools/ask_user.py:37-75`，`should_defer = True`、`is_system_tool = True`、用 `asyncio.Future` 阻塞、`asyncio.wait_for(timeout=300)` 兜底；超时返回 `User did not respond within 5 minutes`。
- [x] Tool 的 `params_model` 全用 Pydantic `BaseModel`，`get_schema()` 通过 `params_model.model_json_schema()` 自动出 JSON Schema。

## 2. 接入完整性（必查，杜绝死代码）

- [x] `create_default_registry` 在 `mewcode/app.py:28` 与 `tests/test_agent.py` 多处中被调用（`git grep -n 'create_default_registry'` 命中 ≥ 6 处）。
- [x] `ToolSearchTool` 在 `mewcode/app.py:67` 被注册并消费 `provider.protocol`。
- [x] `AskUserTool` 在 `mewcode/app.py:68` 被注册，并由 `app.py:pending_ask_user_event` 暴露 `_pending_event`。
- [x] `ToolRegistry.get_all_schemas` 接入点在 `mewcode/agent.py:187`（`git grep -n 'get_all_schemas' mewcode/agent.py`）。
- [x] `ToolRegistry.get` 接入点在 `mewcode/agent.py:234`，`tool.execute` 调用点在 `mewcode/agent.py:248`，证明工具执行接进 Agent Loop。
- [x] `get_deferred_tool_names` 在 `mewcode/agent.py:191` 被消费用于拼 system reminder（`git grep -n 'get_deferred_tool_names' mewcode/agent.py`）。
- [x] `partition_tool_calls` 在 `mewcode/agent.py:60-73` 用 `tool.is_concurrency_safe` 把 ReadFile / Glob / Grep 等只读工具并发分批。
- [x] `StreamEvent` / `ToolCallComplete` / `TextDelta` 等流式事件类型被 `mewcode/agent.py` 与 `mewcode/client.py` 共享。

## 3. 编译与测试

- [x] `python -m compileall mewcode` 通过，无 SyntaxError。
- [x] `ruff check mewcode/tools/ mewcode/agent.py mewcode/app.py mewcode/cache.py` 无报错。
- [x] `pytest tests/test_agent.py -q` 通过：61 个测试用例全绿（含 `test_single_step_tool_call` / `test_multi_step_autonomous` 用 `create_default_registry()` 验证 ReadFile / WriteFile 接通）。
- [x] 工具单元测试：ReadFile (3)、WriteFile (1)、EditFile (3)、Bash (2)、Glob (2)、Grep (3)、ToolRegistry (8)、ToolSearch (3) 全部通过。

## 4. 端到端验证

- [x] Agent Loop 通过 `registry.get_all_schemas(protocol)` 取工具 schema 传给 LLM，LLM 返回的 `ToolCallComplete` 被解析后通过 `registry.get(name)` 查工具、`params_model.model_validate(args)` 校验参数、`await tool.execute(params)` 执行（61 个测试中 `test_single_step_tool_call` / `test_multi_step_autonomous` 覆盖完整路径）。
- [x] 在 TUI 中 Agent 能调用 Bash 工具执行 `echo hello`，输出含 `STDOUT: hello`（`python -m mewcode` 手动测试通过）。
- [x] 留存证据: 61 个测试全绿 + end-to-end Bash 调用成功。

## 5. 文档

- [x] spec.md / tasks.md / checklist.md 三件套齐全（`ls docs/ch03/`）。
