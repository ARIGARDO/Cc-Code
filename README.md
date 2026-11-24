<div align="center">
  <img src="cccode/web/static/cccode-avatar.png" alt="CcCode 头像" width="120">
  <h1>CcCode</h1>
  <p>在本地工作区中使用的 AI 编程助手</p>
  <p>对话式网页界面 · 工具调用 · 权限确认 · 项目记忆</p>
</div>

CcCode 帮助你理解项目、修改代码和运行开发任务。它在本机启动浏览器界面，通过配置的模型生成回答，并根据任务调用文件、搜索、命令等工具。工具执行过程和权限请求会显示在对话中。

> 项目仍在迭代。运行命令或修改文件前，请检查工作区和权限模式，并审阅 Agent 的改动。

## 能做什么

- **对话与工具**：流式显示回答，将思考和工具调用归入可展开的执行过程。
- **工作区与会话**：切换本地项目文件夹，查看和恢复该项目的对话历史。
- **权限控制**：按模式处理文件操作和命令，必要时在页面请求确认。
- **长期记忆与上下文**：加载项目指令和记忆，支持会话持久化、工具结果预算及上下文压缩。
- **扩展能力**：支持技能、MCP 工具、Hooks 和子 Agent；内置 `commit`、`review`、`test` 等技能。
- **两种界面**：默认使用浏览器，也可通过 `--tui` 启动终端界面。

```text
  浏览器 / TUI
       │
       ▼
  Agent 循环 ── 模型服务
       │
       ├── 文件、搜索与命令工具 ── 权限检查
       ├── 技能与 MCP 扩展
       └── 会话、记忆与上下文管理
```

## 快速开始

### 1. 安装

需要 Python 3.11 或更高版本，以及可用的模型服务和 API Key。

```bash
git clone https://github.com/ARIGARDO/Cc_code.git
cd Cc_code
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Windows 用户可使用 `.venv\Scripts\activate` 激活虚拟环境。

### 2. 配置模型

在项目根目录创建 `config.yaml`，例如使用 Anthropic 协议：

```yaml
providers:
  - protocol: anthropic
    model: claude-sonnet-4-6
    thinking: true
```

在启动前设置环境变量 `ANTHROPIC_API_KEY`。也可以在配置中填写 `api_key` 和可选的 `base_url`；`config.yaml` 已被 Git 忽略，请勿将密钥提交到仓库。

使用 OpenAI 协议时，将 `protocol` 设置为 `openai`、填写对应模型，并设置 `OPENAI_API_KEY`。该接入使用 OpenAI Responses API；其他兼容服务需要支持相应协议。当前使用 `providers` 中的第一个配置。

### 3. 启动

```bash
python -m cccode
```

浏览器访问 **http://127.0.0.1:8765**。服务只监听本机。终端界面可使用：

```bash
python -m cccode --tui
```

## 使用指南

1. 点击左侧工作区，输入项目文件夹的完整路径并确认。初始工作区为启动程序时所在的目录。
2. 在输入框描述任务；Agent 会显示回答、工具调用和必要的权限请求。
3. 点击“新建对话”开启新会话；左侧列表可切回已保存的会话。
4. 输入 `/` 查看命令建议，输入 `/skill` 查看技能相关选项。常用命令包括 `/help`、`/status`、`/memory` 和 `/skill`。

项目会话与项目记忆保存在工作区的 `.cccode/`，用户级记忆保存在 `~/.cccode/`。项目指令可放在 `CCCODE.md`。技能可从工作区或用户目录的 `.cccode/skills/` 加载。

权限模式可以在输入框下方切换。权限检查不等于操作系统级沙箱；尤其在允许执行命令时，请确认工作区和操作内容符合预期。

## 开发与测试

```bash
pip install -e ".[dev]"
pytest -q
```

Web 集成测试需要绑定本地端口；部分功能测试使用模拟模型和临时目录，真实模型及 MCP 服务仍需按实际配置验证。

```text
cccode/
├── agent.py          Agent 循环
├── client.py         模型客户端
├── conversation.py   对话与消息
├── web/              浏览器界面与服务
├── tools/            工具实现与注册
├── permissions/      权限检查
├── memory/           会话与长期记忆
├── context/          上下文管理
├── skills/           技能加载与执行
├── mcp/              MCP 客户端
└── agents/、team/    子 Agent 与团队协作
```
