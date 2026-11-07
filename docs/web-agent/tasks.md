# 实施任务

1. 梳理现有界面和事件：`cccode/app.py`、`cccode/agent.py`；无依赖。
2. 定义浏览器协议和本机服务：`cccode/web/`；依赖 1。
3. 复用 Agent 初始化、权限及会话：`cccode/web/`、`cccode/app.py`；依赖 2。
4. 创建对话和工具展示界面：`cccode/web/static/`；依赖 2。
5. 接入权限、提问、停止和命令交互：`cccode/web/`；依赖 3、4。
6. 更新入口、打包与使用说明：`cccode/__main__.py`、`pyproject.toml`、`README.md`；依赖 3–5。
7. 接入主流程：启动浏览器服务并验证真实 Agent 事件链路；依赖 3–6。
8. 端到端验证：覆盖模拟 Agent 对话、工具和权限流程并检查界面；依赖 7。
