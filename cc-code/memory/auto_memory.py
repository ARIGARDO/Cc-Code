"""Automatic memory extraction from conversation history."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from mewcode.conversation import ConversationManager

logger = logging.getLogger(__name__)

USER_MEMORIES_RELPATH = ".mewcode/memories.md"
PROJECT_MEMORIES_RELPATH = ".mewcode/memories.md"

MEMORY_EXTRACTION_PROMPT = """你是一个记忆提取助手。请仔细阅读以下对话，提取值得长期记忆的信息。

## 分类说明
- 用户偏好：用户的个人信息、身份背景、使用习惯、偏好设置、目标期望等。例如"我是学生"、"我想往Agent方向发展"、"我想要20k月薪"、"我喜欢简洁的代码风格"等。
- 纠正反馈：用户对之前回答的纠正或反馈。例如"不要用Java"、"这个答案不对"等。
- 项目知识：项目特定的技术细节、架构信息、代码约定等。
- 参考资料：用户提到的文档、链接、参考资源等。

## 要求
1. 仔细识别用户明确表达的个人信息（身份、背景、目标、偏好），将这些归入"用户偏好"
2. 不要重复添加已有的记忆条目
3. 如果某个分类下没有值得记忆的内容，不要输出该分类（整段省略）
4. 每个条目以 "- " 开头
5. 不要调用任何工具
6. 输出格式为 ### 分类标题 开头，每个分类之间空一行

## 当前已有记忆
{current_memories}

## 最近对话
{conversation}

请输出完整的 memories.md 文件内容（包含所有有内容的分类标题）："""

_USER_LEVEL_HEADERS = {"用户偏好", "纠正反馈"}
_PROJECT_LEVEL_HEADERS = {"项目知识", "参考资料"}


_MEMORY_TRIGGER_PATTERNS = (
    "我是", "我叫", "我的名字", "我姓",
    "我喜欢", "我不喜欢", "我偏好", "我习惯",
    "我想", "我要", "我希望", "我需要",
    "我是学生", "我是工程师", "我是开发",
    "我的专业", "我的方向", "我的目标",
    "不要用", "别用", "不要这样", "不要那样",
    "记住", "记住我", "别忘了",
    "我正在学", "我正在做", "我在准备",
    "月薪", "薪资", "工资", "就业",
    "跨考", "跨专业", "零基础",
)


def should_trigger_extraction(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _MEMORY_TRIGGER_PATTERNS)


class MemoryManager:
    def __init__(self, project_root: str | Path) -> None:
        self._user_path = Path.home() / USER_MEMORIES_RELPATH
        self._project_path = Path(project_root) / PROJECT_MEMORIES_RELPATH
        self._last_extraction_msg_count: int = 0

    @property
    def user_path(self) -> Path:
        return self._user_path

    @property
    def project_path(self) -> Path:
        return self._project_path

    def load(self) -> str:
        parts: list[str] = []
        for label, path in [("[用户级·跨项目]", self._user_path), ("[项目级]", self._project_path)]:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"{label}\n{text}")
        return "\n\n".join(parts)

    async def extract(
        self,
        client: Any,
        conversation: ConversationManager,
    ) -> None:
        try:
            # Skip injected system messages (env context, instructions, memory)
            skip_count = 0
            if conversation.env_injected:
                skip_count += 1
            if conversation.ltm_injected:
                skip_count += 2

            msg_start = max(self._last_extraction_msg_count, skip_count)
            history = conversation.history[msg_start:]
            if not history:
                logger.debug("Memory extraction: no new messages since last extraction (skipped %d injected)", skip_count)
                return

            lines: list[str] = []
            for msg in history[-20:]:
                role_label = "用户" if msg.role == "user" else "助手"
                text = msg.content[:500] if msg.content else ""
                if text:
                    lines.append(f"{role_label}: {text}")

            if not lines:
                logger.debug("Memory extraction: no extractable content after filtering")
                return

            current_memories = self.load() or "(空)"

            prompt = MEMORY_EXTRACTION_PROMPT.format(
                current_memories=current_memories,
                conversation="\n".join(lines),
            )

            from mewcode.conversation import ConversationManager as CM
            conv = CM()
            conv.add_user_message(prompt)

            collected = ""
            stream = client.stream(conv, system="你是一个记忆提取助手。", tools=None)
            async for event in stream:
                from mewcode.tools.base import TextDelta
                if isinstance(event, TextDelta):
                    collected += event.text
                    logger.debug("Memory extraction got delta: %r", event.text[:50])

            logger.info("Memory extraction complete, collected %d chars", len(collected))
            if collected.strip():
                self._write_memories(collected)
                self._last_extraction_msg_count = len(conversation.history)
            else:
                logger.debug("Memory extraction: no content collected")
        except Exception as e:
            logger.exception("Memory extraction failed with exception: %s", e)

    def _write_memories(self, content: str) -> None:
        import re
        sections = re.split(r"\n(?=#{2,3} )", content)
        user_sections: list[str] = []
        project_sections: list[str] = []

        for section in sections:
            section = section.strip()
            if not section:
                continue
            header_line = section.split("\n")[0].strip()
            header = re.sub(r"^#+\s*", "", header_line)
            body = "\n".join(section.split("\n")[1:])
            assigned = MemoryManager._assign_section(header, body)
            if assigned is not None:
                dest, text = assigned
                if dest == "user":
                    user_sections.append(text)
                elif dest == "project":
                    project_sections.append(text)

        if user_sections:
            self._user_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_path(self._user_path, user_sections)

        if project_sections:
            self._project_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_path(self._project_path, project_sections)

    @staticmethod
    def _write_path(path: Path, sections: list[str]) -> None:
        new_sections = MemoryManager._parse_sections("\n\n".join(sections))

        existing_sections: dict[str, list[str]] = {}
        if path.is_file():
            existing_text = path.read_text(encoding="utf-8").strip()
            if existing_text:
                existing_sections = MemoryManager._parse_sections(existing_text)

        merged: dict[str, list[str]] = {}
        for header in dict.fromkeys(list(existing_sections.keys()) + list(new_sections.keys())):
            existing_items = existing_sections.get(header, [])
            new_items = new_sections.get(header, [])
            seen = set(existing_items)
            merged[header] = existing_items + [item for item in new_items if item not in seen]

        parts: list[str] = []
        for header, items in merged.items():
            if items:
                parts.append(f"### {header}\n" + "\n".join(items))

        if parts:
            path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")

    @staticmethod
    def _parse_sections(text: str) -> dict[str, list[str]]:
        import re
        result: dict[str, list[str]] = {}
        chunks = re.split(r"\n(?=#{2,3} )", text.strip())
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            header_line = chunk.split("\n")[0].strip()
            header = re.sub(r"^#+\s*", "", header_line)
            items = [
                line.strip() for line in chunk.split("\n")[1:]
                if line.strip().startswith("- ") and not MemoryManager._is_placeholder(line)
            ]
            if items:
                result.setdefault(header, []).extend(items)
        return result

    @staticmethod
    def _is_placeholder(line: str) -> bool:
        stripped = line.lstrip("- ").strip()
        return stripped in {"", "...", "…", "无", "暂无", "N/A"}

    @staticmethod
    def _assign_section(header: str, body: str) -> Optional[tuple[str, str]]:
        real_lines = [
            line for line in body.split("\n")
            if line.strip().startswith("- ") and not MemoryManager._is_placeholder(line)
        ]
        if not real_lines:
            return None

        text = f"### {header}\n" + "\n".join(real_lines)

        for kw in _USER_LEVEL_HEADERS:
            if kw in header:
                return ("user", text)

        for kw in _PROJECT_LEVEL_HEADERS:
            if kw in header:
                return ("project", text)

        return ("project", text)

    def clear(self) -> None:
        for path in [self._user_path, self._project_path]:
            if path.exists():
                path.write_text("", encoding="utf-8")

    def get_display_text(self) -> str:
        parts: list[str] = []
        for label, path in [("[用户级]", self._user_path), ("[项目级]", self._project_path)]:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"{label} {path}\n{text}")

        if not parts:
            return "当前没有任何自动记忆。"

        return "\n\n".join(parts)


def extract_and_store_memory(
    memory_manager: Any,
    conversation: ConversationManager,
) -> None:
    """Extract key facts from the conversation and store them in long-term memory.

    Called periodically (every MEMORY_EXTRACTION_INTERVAL iterations).
    """
    if memory_manager is None:
        return
    if not hasattr(memory_manager, "extract"):
        return
    import asyncio
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(memory_manager.extract(None, conversation))
    else:
        loop.run_until_complete(memory_manager.extract(None, conversation))