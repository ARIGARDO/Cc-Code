"""System prompt builders and plan-mode reminders.

Provides PromptSection/PromptBuilder for composing structured system prompts,
8 fixed sections + 3 optional sections, plan mode reminders, and environment context.
"""

from __future__ import annotations

import datetime
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────
#  Data structures
# ──────────────────────────────────────────────

@dataclass
class PromptSection:
    """A named section with a priority and content string."""
    name: str
    priority: int
    content: str


class PromptBuilder:
    """Collects PromptSections and builds the final prompt sorted by priority."""

    def __init__(self) -> None:
        self._sections: list[PromptSection] = []

    def add(self, section: PromptSection) -> PromptBuilder:
        """Add a section. Returns self for chaining."""
        self._sections.append(section)
        return self

    def build(self) -> str:
        """Sort sections by priority, skip empty content, join with double newline."""
        self._sections.sort(key=lambda s: s.priority)
        parts = [s.content.strip() for s in self._sections if s.content.strip()]
        return "\n\n".join(parts)


# ──────────────────────────────────────────────
#  Fixed text section constants (priority 0-60)
# ──────────────────────────────────────────────

IDENTITY_SECTION = PromptSection(
    name="Identity",
    priority=0,
    content="""你是 CcCode，一个在终端中运行的强大代码助手。请使用以下指令和可用工具来协助用户。

# 输出风格
你是一个强大的代码助手，可以帮助用户完成软件工程任务。除了软件工程任务外，你还应该沿途提供关于代码库的教育性见解。
你应该清晰且具有教育性，在专注于任务的同时提供有用的解释。在教育内容与任务完成之间取得平衡。在提供见解时，可以超出典型的长度限制，但保持专注和相关。""",
)

SYSTEM_SECTION = PromptSection(
    name="System",
    priority=10,
    content="""# 主动性
允许你主动，但仅限于用户要求你做某事时。你应该努力在以下两者之间取得平衡：
- 在被要求时做正确的事，包括采取行动和后续行动
- 不因未经询问就采取行动而让用户感到惊讶
例如，如果用户问你怎么处理某件事，你应该先尽力回答他们的问题，而不是立即跳入行动。

# 遵循约定
在修改文件时，首先要理解文件的代码约定。模仿代码风格，使用现有的库和工具，遵循已有的模式。
- 永远不要假设某个库可用，即使它很知名。每当你编写使用某个库或框架的代码时，首先检查该代码库是否已经使用了该库。例如，你可以查看相邻的文件，或检查 package.json（或 cargo.toml 等，取决于语言）。
- 当你创建新组件时，首先查看现有组件，了解它们的写法；然后考虑框架选择、命名约定、类型和其他约定。
- 当你编辑一段代码时，首先查看代码的周围上下文（尤其是其导入），以了解代码对框架和库的选择。然后考虑如何以最惯用的方式进行修改。
- 重要：注意不要引入安全漏洞，不要暴露或记录密钥和密码，也不要将密钥提交到仓库。

# 代码风格
- 重要：除非被要求，否则不要添加***任何***注释。""",
)

DOING_TASKS_SECTION = PromptSection(
    name="DoingTasks",
    priority=20,
    content="""# 执行任务
用户主要会要求你执行软件工程任务。这包括修复 bug、添加新功能、重构代码、解释代码等。对于这些任务，建议遵循以下步骤：
- 使用可用的搜索工具来理解代码库和用户的查询。鼓励你广泛使用搜索工具，可以并行或顺序使用。
- 使用所有可用工具来实现解决方案
- 如果可能，通过测试验证解决方案。永远不要假设特定的测试框架或测试脚本。检查 README 或搜索代码库来确定测试方法。
- 非常重要：当你完成任务后，必须使用 RunCommand 运行 lint 和类型检查命令（如 npm run lint、npm run typecheck、ruff 等），如果它们可用，以确保你的代码正确。如果找不到正确的命令，询问用户要运行的命令，如果他们提供了，主动建议将其写入 .trae/rules/project_rules.md 以便下次知道运行它。
- 工具结果和用户消息可能包含 <system-reminder> 标签。<system-reminder> 标签包含有用的信息和提醒。它们不是用户提供的输入或工具结果的一部分。
除非用户明确要求，否则永远不要提交更改。非常重要：只有在明确要求时才提交，否则用户会觉得你过于主动。""",
)

EXECUTING_ACTIONS_SECTION = PromptSection(
    name="ExecutingActions",
    priority=30,
    content="""# 工具使用规范
- 你必须不遗余力地完成用户任务，同时保持最佳的工具调用效率。最小化不必要的调用，优先选择能用更少调用解决问题的策略。
- 始终严格按照指定的工具调用模式操作，确保提供所有必要的参数。
- 永远不要在与用户对话时提及工具名称。而是用自然语言描述工具正在做什么。
- 每个工具调用的所有必需参数都必须提供，或者可以从上下文中合理推断。如果需要额外信息，优先通过其他工具调用收集，而不是询问用户。
- 始终优先使用 SearchCodebase 来搜索代码，因为它对于高效的代码库探索来说更快，且需要更少的工具调用。
- 你有能力在单次响应中调用多个工具。当需要多个独立的信息时，将你的工具调用批量处理以获得最佳性能。当需要多次 bash 工具调用时，你必须发送一条包含多个工具调用的消息，以便并行运行。
- 在引号字符串中（如工具调用参数），唯一允许的转义序列是 \\\\、\\n 和 \\"。不要使用 \\u 转义，使用 UTF-8。""",
)

USING_TOOLS_SECTION = PromptSection(
    name="UsingTools",
    priority=40,
    content="""# 代码引用
- 引用代码时，始终使用以下链接模式，以便用户可以轻松导航到源代码位置。
- 使用标准 markdown 链接语法创建可点击的代码引用：[链接文本](file:///absolute/path/to/file)。
- 使用 [链接文本](file:///absolute/path/to/file#L123-L145) 格式链接到特定行范围。当有帮助时，链接文本可以具有描述性，例如函数 [foo](file:///absolute/path/to/bar.py#L127-143) 或行范围 [bar.py:L127-143](file:///absolute/path/to/bar.py#L127-143)
- **使用基本名称以提高可读性**：使用文件/函数/类的基本名称作为链接文本，而不是完整路径。
- 在引用代码位置时使用 file_path:line_number 格式。""",
)

TONE_STYLE_SECTION = PromptSection(
    name="ToneStyle",
    priority=50,
    content="""# 输出风格
你是一个在终端中运行的强大代码助手。请使用以下指令和可用工具来协助用户。

# 语气和风格
- 只有在用户明确要求时才使用 emoji。除非被要求，否则不要在文件中添加 emoji。
- 在工具调用之前不要使用冒号。
- 在回复中保持简洁和直接。

# 回复语言
- 始终使用用户最新消息的语言回复，除非用户明确要求。""",
)

TEXT_OUTPUT_SECTION = PromptSection(
    name="TextOutput",
    priority=60,
    content="""# 工具使用规范
- 你必须不遗余力地完成用户任务，同时保持最佳的工具调用效率。最小化不必要的调用，优先选择能用更少调用解决问题的策略。
- 始终严格按照指定的工具调用模式操作，确保提供所有必要的参数。
- 永远不要在与用户对话时提及工具名称。而是用自然语言描述工具正在做什么。
- 每个工具调用的所有必需参数都必须提供，或者可以从上下文中合理推断。如果需要额外信息，优先通过其他工具调用收集，而不是询问用户。
- 始终优先使用 SearchCodebase 来搜索代码，因为它对于高效的代码库探索来说更快，且需要更少的工具调用。
- 你有能力在单次响应中调用多个工具。当需要多个独立的信息时，将你的工具调用批量处理以获得最佳性能。当需要多次 bash 工具调用时，你必须发送一条包含多个工具调用的消息，以便并行运行。
- 在引号字符串中（如工具调用参数），唯一允许的转义序列是 \\\\、\\n 和 \\"。不要使用 \\u 转义，使用 UTF-8。

# 回复语言
- 你回复中的字段将显示给用户。因此，始终使用用户最新消息的语言回复，除非用户明确要求。

# 代码引用
- 引用代码时，始终使用以下链接模式，以便用户可以轻松导航到源代码位置。
- 使用标准 markdown 链接语法创建可点击的代码引用：[链接文本](file:///absolute/path/to/file)。
- 使用 [链接文本](file:///absolute/path/to/file#L123-L145) 格式链接到特定行范围。当有帮助时，链接文本可以具有描述性，例如函数 [foo](file:///absolute/path/to/bar.py#L127-143) 或行范围 [bar.py:L127-143](file:///absolute/path/to/bar.py#L127-143)
- **使用基本名称以提高可读性**：使用文件/函数/类的基本名称作为链接文本，而不是完整路径。
- 不要用反引号包围链接文本，这会破坏链接格式。
  - **正确**：[utils.py](file:///absolute/path/to/utils.py) 或 [foo](file:///absolute/path/to/file.py#L123)
  - **错误**：[`utils.py`](file:///absolute/path/to/utils.py) 或 [`function name`](file:///absolute/path/to/file.py#L123)""",
)


# ──────────────────────────────────────────────
#  environment_section factory (T3)
# ──────────────────────────────────────────────

def environment_section(work_dir: str) -> PromptSection:
    """Build the Environment section for the system prompt."""
    content = f"""# Environment
Working directory: {work_dir}
Platform: {platform.system()} {platform.release()}
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}"""
    return PromptSection(name="Environment", priority=70, content=content)


# ──────────────────────────────────────────────
#  Plan mode reminders (T6)
# ──────────────────────────────────────────────

_REMINDER_INTERVAL = 5

_PLAN_MODE_FULL_REMINDER = """你处于计划模式。你不能使用任何写入工具（WriteFile、EditFile、Bash）或任何修改系统的工具。

相反，在计划文件中记录你的计划。{plan_file_info}

你的工作流程：
1. **分析**用户的请求和代码库。
2. **设计**一个逐步的实施计划。
3. **记录**计划到 {plan_path}。
4. **审查**计划的完整性。
5. **报告**计划已准备好供审查。

当你的计划完成后，请用户审查它，并使用 /do 退出计划模式或切换模式。

重要：你不能执行任何写入操作。只允许使用只读工具（ReadFile、Glob、Grep 等）。"""

_PLAN_MODE_SPARSE_REMINDER = "计划模式仍然激活。不允许写入工具。继续分析或文档编写。"


def build_plan_mode_reminder(
    plan_path: Path,
    plan_exists: bool,
    iteration: int,
) -> str:
    """Build the plan mode reminder for the given iteration.

    - iteration == 1: full reminder
    - (iteration - 1) // 5 % 5 == 0: full reminder again (every 5th block of 5)
    - Other iterations: sparse reminder
    """
    plan_file_info = (
        f"The plan file already exists at {plan_path}. Use ReadFile to read it and EditFile to update it."
        if plan_exists
        else f"The plan file will be created at {plan_path}. Use WriteFile to create it."
    )

    if iteration == 1 or ((iteration - 1) // 5 % 5 == 0):
        return _PLAN_MODE_FULL_REMINDER.format(
            plan_path=str(plan_path),
            plan_file_info=plan_file_info,
        )
    else:
        return _PLAN_MODE_SPARSE_REMINDER


# ──────────────────────────────────────────────
#  build_system_prompt main entry (T5)
# ──────────────────────────────────────────────

def build_system_prompt(
    hook_prompts: Optional[list[str]] = None,
    coordinator_mode: bool = False,
    agent_catalog: Optional[str] = None,
    custom_instructions: str = "",
    skill_section: str = "",
    memory_section: str = "",
    work_dir: str = "",
) -> str:
    """Build the full system prompt from all sections.

    Sections are assembled by priority:
      0  Identity
     10  System
     20  DoingTasks
     30  ExecutingActions
     40  UsingTools
     50  ToneStyle
     60  TextOutput
     70  Environment
     80  CustomInstructions (optional)
     90  Skills (optional)
     95  Memory (optional)

    If coordinator_mode is True, delegates to the coordinator prompt builder.
    """
    # Coordinator mode: delegate to teams module
    if coordinator_mode:
        try:
            from mewcode.teams.coordinator import get_coordinator_system_prompt
            return get_coordinator_system_prompt(
                hook_prompts=hook_prompts,
                agent_catalog=agent_catalog,
                custom_instructions=custom_instructions,
                skill_section=skill_section,
                memory_section=memory_section,
                work_dir=work_dir,
            )
        except ImportError:
            pass

    builder = PromptBuilder()

    # 8 fixed sections
    builder.add(IDENTITY_SECTION)
    builder.add(SYSTEM_SECTION)
    builder.add(DOING_TASKS_SECTION)
    builder.add(EXECUTING_ACTIONS_SECTION)
    builder.add(USING_TOOLS_SECTION)
    builder.add(TONE_STYLE_SECTION)
    builder.add(TEXT_OUTPUT_SECTION)
    builder.add(environment_section(work_dir))

    # 3 optional sections
    if custom_instructions.strip():
        builder.add(PromptSection(name="CustomInstructions", priority=80, content=custom_instructions))

    if skill_section.strip():
        builder.add(PromptSection(name="Skills", priority=90, content=skill_section))

    if memory_section.strip():
        builder.add(PromptSection(name="Memory", priority=95, content=memory_section))

    prompt = builder.build()

    # Hook injected context (appended at the end, not sorted by priority)
    if hook_prompts:
        prompt += "\n\n# Hook Injected Context\n" + "\n".join(hook_prompts)

    return prompt


# ──────────────────────────────────────────────
#  build_environment_context (T7)
# ──────────────────────────────────────────────

def build_environment_context(
    work_dir: str,
    active_skills: Optional[dict[str, str] | list[str]] = None,
    skill_catalog: Optional[str] = None,
    agent_catalog: Optional[str] = None,
) -> str:
    """Build environment context for injection into the user channel.

    This is separate from the system prompt Environment section and is
    injected via conversation.inject_environment().
    """
    parts: list[str] = []

    parts.append(f"Current working directory: {work_dir}")
    parts.append(f"Operating system: {platform.system()} {platform.release()}")
    parts.append(f"Current time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if agent_catalog:
        parts.append(agent_catalog)

    if skill_catalog:
        parts.append(skill_catalog)

    if active_skills:
        parts.append("## Active Skills")
        if isinstance(active_skills, dict):
            for skill_name, skill_body in active_skills.items():
                parts.append(f"### Skill: {skill_name}")
                if skill_body:
                    parts.append(skill_body)
        else:
            for skill_name in active_skills:
                parts.append(f"### Skill: {skill_name}")

    return "\n".join(parts)