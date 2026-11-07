# CcCode

一个基于 Python 构建的终端 AI 编程助手，设计灵感来自 Claude Code。

CcCode 提供基于 Textual 的交互式 TUI 界面，通过与 LLM 对话来辅助软件工程任务——直接在终端中阅读、编写、搜索和编辑代码。

## 功能特性

- **LLM 多供应商** — 通过统一流式接口支持 Anthropic (Claude) 和 OpenAI，支持 Extended Thinking。
- **Agent 循环** — 自主工具调用 Agent，可读取文件、执行 Shell 命令、搜索代码和编辑文件。
- **权限系统** — 多模式权限控制（default / accept-edits / plan / bypass / custom），支持沙箱化文件访问。
- **MCP 支持** — 集成 Model Context Protocol，可扩展外部工具提供者。
- **团队协作** — 基于邮箱消息传递的多 Agent 协调机制。
- **技能系统** — 可复用的 Agent 技能（commit / review / test / backend-interview），支持内置与自定义技能。
- **Hooks 系统** — 事件驱动的钩子系统，在 Agent 生命周期事件上实现自定义自动化。
- **记忆系统** — 基于会话的对话记忆，支持自动记忆提取。
- **上下文压缩** — 长会话中自动压缩上下文，确保不超出 Token 限制。

## 技术栈

- **语言**：Python 3.11+
- **TUI**：[Textual](https://textual.textualize.io/)
- **LLM SDK**：Anthropic Python SDK、OpenAI Python SDK
- **数据校验**：Pydantic、jsonschema
- **MCP**：mcp >= 1.0.0

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- Anthropic API Key（`ANTHROPIC_API_KEY`）或 OpenAI API Key（`OPENAI_API_KEY`）

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd cccode

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e .
```

### 配置

在项目根目录创建 `config.yaml`：

```yaml
providers:
  - protocol: anthropic
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}
    thinking: true
```

### 运行

```bash
python -m cccode
```

### 从旧名称迁移

新版本使用 `.cccode/` 保存运行数据，读取 `CCCODE.md` 项目指令，并使用 `CCCODE_COORDINATOR_MODE` 环境变量。已有安装可将项目目录及用户主目录下的 `.mewcode/` 复制到对应的 `.cccode/`，将需要保留的 `MEWCODE.md` 复制为 `CCCODE.md`。若目标已存在，请先检查并按需合并，避免覆盖现有数据。迁移前建议备份数据；旧目录不会自动删除。

## 项目结构

```
cccode/
├── cccode/                   # 主应用包
│   ├── __main__.py           # 入口（python -m cccode）
│   ├── app.py                # Textual TUI 应用
│   ├── agent.py              # Agent 循环（LLM + 工具执行）
│   ├── client.py             # LLM 客户端抽象层（Anthropic/OpenAI）
│   ├── config.py             # 配置管理
│   ├── conversation.py       # 对话管理器与消息模型
│   ├── agents/               # 子 Agent 与 Fork 管理
│   ├── commands/             # 斜杠命令（/help、/compact 等）
│   ├── context/              # 上下文窗口与压缩
│   ├── hooks/                # 事件驱动钩子系统
│   ├── mcp/                  # MCP 客户端与工具集成
│   ├── memory/               # 会话记忆与自动记忆
│   ├── permissions/          # 权限检查与沙箱
│   ├── skills/               # 技能系统（内置 + 自定义）
│   ├── team/                 # 多 Agent 团队协作
│   └── tools/                # 工具注册中心与实现
├── docs/                     # 设计文档（ch02 - ch15）
│   └── chXX/
│       ├── spec.md           # 功能规格说明
│       ├── tasks.md          # 实现任务拆分
│       └── checklist.md      # 验收清单
├── tests/                    # 测试套件
├── pyproject.toml            # 项目元数据与依赖
├── config.yaml               # 用户配置（已 gitignore）
└── CCCODE.md                 # AI 助手的项目约定
```

## 开发指南

### 环境搭建

```bash
pip install -e ".[dev]"
```

### 代码检查与格式化

```bash
ruff check cccode/ tests/
ruff format cccode/ tests/
```

### 类型检查

```bash
mypy cccode/
```

### 运行测试

```bash
pytest
```

## 设计文档

设计文档按章节组织在 `docs/` 目录中，每章覆盖一个特定功能领域：

| 章节 | 功能 |
|------|------|
| ch02 | LLM 客户端与对话管理 |
| ch03 | 工具系统与注册中心 |
| ch04 | Agent 循环 |
| ch05 | 权限系统 |
| ch06 | TUI 界面（Textual） |
| ch07 | MCP 集成 |
| ch08 | 上下文压缩 |
| ch09 | 记忆系统 |
| ch10 | Hooks 系统 |
| ch11 | 技能系统 |
| ch12 | 团队协作 |
| ch13 | 子 Agent |
| ch14 | 命令与补全 |
| ch15 | 计划与任务管理 |

## License

MIT
