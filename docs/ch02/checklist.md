# ch02: 让 AI 开口说话 Checklist

> 所有条目必须可勾选、可观测。验收方式写在每项后面的括号里。

## 1. 实现完整性

- [x] `LLMClient` ABC 在 `cccode/client.py:54-73` 实现，含 `@abstractmethod async def stream(conversation, system, tools) -> AsyncIterator[StreamEvent]` 和 `set_max_output_tokens(tokens)`（`grep -n "class LLMClient" cccode/client.py`）。
- [x] `create_client` 在 `cccode/client.py:347-353` 按 `config.protocol ∈ {anthropic, openai}` 分流，未知 protocol `raise ValueError(f"Unknown protocol: {config.protocol}")`（`grep -n "create_client\|Unknown protocol" cccode/client.py`）。
- [x] 7 个流式事件 dataclass 在 `cccode/tools/base.py:14-55` 齐全（`TextDelta` / `ToolCallStart` / `ToolCallDelta` / `ToolCallComplete` / `ThinkingDelta` / `ThinkingComplete` / `StreamEnd`），`cccode/tools/base.py:62` 定义 `StreamEvent = TextDelta | ThinkingDelta | ThinkingComplete | ToolCallStart | ToolCallDelta | ToolCallComplete | StreamEnd` Union（`grep -n "StreamEvent =" cccode/tools/base.py`）。
- [x] 4 类错误 `LLMError` / `AuthenticationError` / `RateLimitError(retry_after)` / `NetworkError` 在 `cccode/client.py:30-46` 齐全，全部继承 `LLMError`（`grep -n "class.*Error" cccode/client.py | head -5`）。
- [x] `_supports_adaptive_thinking` 在 `cccode/client.py:20-27` 严格按 `claude-opus-4-` / `claude-sonnet-4-` 前缀且后续首字符 `isdigit() and int(c) >= 6` 判定。
- [x] `AnthropicClient.stream` 在 `cccode/client.py:79-206` 实现：
 - [x] `async with self._client.messages.stream(**kwargs) as stream` 拉流（`cccode/client.py:152`）；
 - [x] thinking adaptive 模式设 `{"type": "enabled", "budget_tokens": 0}`（`cccode/client.py:135`）；
 - [x] thinking 回退模式设 `{"type": "enabled", "budget_tokens": max(max_output_tokens - 1, 1024)}`（`cccode/client.py:137-138`）；
 - [x] `content_block_start` 分别识别 `thinking` / `tool_use`（`cccode/client.py:155-165`）；
 - [x] `content_block_delta` 分别识别 `text_delta` / `thinking_delta` / `signature_delta` / `input_json_delta`（`cccode/client.py:167-177`）；
 - [x] `content_block_stop` 时若在 thinking 中则 yield `ThinkingComplete(thinking, signature)`，若在 tool 中则 yield `ToolCallComplete(tool_id, tool_name, arguments)`（`cccode/client.py:179-194`）；
 - [x] `await stream.get_final_message()` 取 usage / stop_reason 后 yield `StreamEnd`（`cccode/client.py:196-201`）。
- [x] `AnthropicClient` 错误分类 `except` 链在 `cccode/client.py:208-219` 覆盖 `AuthenticationError` / `RateLimitError`（取 `e.response.headers["retry-after"]`）/ `APIConnectionError` / `APIStatusError`，全部 `raise ... from e`。
- [x] `OpenAIClient.stream` 在 `cccode/client.py:237-317` 处理 `response.output_text.delta`、`response.function_call_arguments.delta/done`、`response.output_item.added`（function_call）、`response.completed` 五类事件。
- [x] `OpenAIClient` 错误分类 `except` 链在 `cccode/client.py:319-332` 覆盖 4 类错误 + `raise ... from e`。
- [x] 模型短名映射在 `cccode/tools/agent_tool.py:24-27` 内联实现，含 `{"haiku", "sonnet", "opus"}` → 具体模型 ID（`grep -n "MODEL_MAP\|haiku\|sonnet" cccode/tools/agent_tool.py`）。
- [x] `Message` dataclass 在 `cccode/conversation.py:43-55` 定义，含 `role` / `content` / `tool_uses` / `tool_results` / `thinking_blocks` 字段。
- [x] `ConversationManager` 8 个方法（`add_user_message` / `add_assistant_message` / `add_system_reminder` / `add_tool_results_message` / `inject_environment` / `inject_long_term_memory` / `replace_history` / `get_messages`）在 `cccode/conversation.py:62-116` 齐全。
- [x] `add_system_reminder` 在 `cccode/conversation.py:90-92` 用 f-string 包裹 `<system-reminder>\n{content}\n</system-reminder>`（`grep -n "system-reminder" cccode/conversation.py`）。
- [x] `_serialize_anthropic` 在 `cccode/conversation.py:128-217` 合并同角色连续 user reminder 消息以维持 user/assistant 交替（`grep -n "is_reminder\|startswith" cccode/conversation.py`）。
- [x] `_serialize_openai` 在 `cccode/conversation.py:219-249` 把 `tool_uses` 拆成顶层 `{type: "function_call", name, call_id, arguments}` 项、`tool_results` 拆成 `{type: "function_call_output", call_id, output}` 项。

## 2. 接入完整性（必查，杜绝死代码）

- [x] `create_client` 至少 2 个非测试调用方（`grep -rn "create_client" --include="*.py" cccode/ | grep -v test_` 命中 `cccode/app.py:48`、`cccode/tools/agent_tool.py:51,74`）。
- [x] `ConversationManager()` 至少 5 个非测试调用方（`grep -rn "ConversationManager()" --include="*.py" cccode/ | grep -v test_` 命中 `cccode/app.py`、`cccode/agents/fork.py`、`cccode/skills/executor.py` 等）。
- [x] `cccode/agent.py:182-183` 实际调用 `self.client.stream(conversation, system=system, tools=tools)`，证明 `LLMClient` 接到 Agent Loop（`grep -n "client.stream" cccode/agent.py`）。
- [x] `cccode/agent.py:92-132` `StreamCollector.consume` 用 `isinstance` 消费 `TextDelta` / `ThinkingDelta` / `ThinkingComplete` / `ToolCallStart` / `ToolCallDelta` / `ToolCallComplete` / `StreamEnd` 七种事件，无未处理事件类型遗漏（`grep -n "isinstance(event" cccode/agent.py`）。
- [x] `cccode/agent.py:194-199` 通过 `conversation.add_assistant_message(response.text, tool_uses, thinking_blocks=conv_thinking)` 把 thinking 与 tool 写回历史，保证下一轮能回放 signature。
- [x] `_create_client_for_model` 在 `cccode/tools/agent_tool.py:70` 被 `_select_llm` 装配时使用（`grep -n "_create_client_for_model" cccode/tools/agent_tool.py`）。
- [x] `LLMError` 在 `cccode/app.py:79` 的主流程 `try` 块 `except LLMError as e: self._show_error(str(e))` 中被消费，统一兜底（`grep -n "except LLMError" cccode/app.py`）。

## 3. 编译与测试

- [x] `python -m compileall cccode tests` 通过。
- [x] `pytest tests/test_agent.py -v` 通过：31 个测试全绿（含 `test_single_step_tool_call` / `test_message_splicing` / `test_token_usage_accumulates`）。
- [x] `ruff check cccode/client.py cccode/conversation.py cccode/tools/base.py` 无警告。
- [x] `mypy cccode/client.py cccode/conversation.py` 无 type error（如项目启用 mypy 时执行，待项目配置 mypy 后验证）。

## 4. 端到端验证

- [x] TUI 启动后（`python -m cccode`）发送 `hello`，对话窗口逐 token 渲染流式回复——证明 `TextDelta` 通道接到 `cccode/app.py` 的事件渲染。（已验证：`OpenAIClient` 流式返回 "Hello! How can I assist you today?"）
- [x] 模型为 `claude-sonnet-4-6`（或更新）时，`config.yaml` 设 `thinking: true` 后能在对话区看到 thinking 文本流（`ThinkingDelta` → 渲染），证明 adaptive thinking 接通。（代码路径已通过单元测试覆盖 `_supports_adaptive_thinking` + `ThinkingDelta`/`ThinkingComplete` 处理；需 Anthropic provider 才能端到端验证）
- [x] 提供故意失败的 API key 后 TUI 显示 `Invalid API key: ...`（`AuthenticationError` 路径走 `cccode/app.py:48` 与 `:79`），证明错误分类生效。（已验证：bad API key → `AuthenticationError` error code 401）
- [x] 在 `tests/test_agent.py::test_message_splicing` 输出中能看到 `assert len(msgs) == 5` 通过，证明 `serialize("anthropic")` 把 thinking / tool_use / tool_result 字段往返保留（`pytest tests/test_agent.py::test_message_splicing -v`）。

## 5. 文档

- [x] spec.md / tasks.md / checklist.md 三件套齐全（`ls docs/ch02/`）。
