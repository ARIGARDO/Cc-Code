# 核心模块检查清单（2026-11-23）

自动测试命令：`pytest -q`。本次结果：577 项通过；使用本地端口运行 Web 集成测试。测试以模拟模型、临时目录和测试服务为主，不代表每个外部模型或 MCP 服务均已实际联通。

- [x] Agent 循环：流式响应、工具调用及结果、重复调用 ID、错误及重试等（`tests/test_agent.py`、`tests/test_harness_regressions.py`、`tests/test_stream_disconnect.py`）。
- [x] 工具系统：工具注册与调用、权限请求、拒绝时不执行、搜索边界（`tests/test_agent.py`、`tests/test_harness_regressions.py`、`tests/test_web.py`）。
- [x] 权限：规则匹配、危险命令、路径隔离及不同模式（`tests/test_permissions.py`）。
- [x] 记忆与会话：持久化、恢复、思考及工具记录恢复、项目切换（`tests/test_memory.py`、`tests/test_web.py`）。
- [x] 上下文：阈值、压缩辅助、长工具结果保存与替换（`tests/test_context.py`、`tests/test_replacement_state.py`）。
- [x] 技能：加载、优先级、重载、工具过滤、调用与隔离；网页 `/skill` 提示和命令执行（`tests/test_skills.py`、`tests/test_web.py`）。
- [x] 命令、MCP、钩子、子智能体和团队：已有自动化用例（`tests/test_commands.py`、`tests/test_mcp.py`、`tests/test_hooks.py`、`tests/test_subagent.py`、`tests/test_team_system.py`）。
- [ ] 真实模型端到端：在网页选择隔离的测试项目，发送任务，确认流式回复、工具许可与执行结果，再切换会话检查恢复。
- [ ] 实际技能验收：在网页输入 `/skill`，确认出现技能建议；选择技能执行并检查模型响应。
- [ ] 配置具体 MCP 服务后，验证连接、工具发现、执行和断线恢复。
- [ ] 使用真实长对话验证达到阈值后的压缩，以及跨重启记忆效果。

用户本机配置、第三方模型与 MCP 服务未在本次自动测试中验证。
