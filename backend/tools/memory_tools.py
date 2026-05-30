"""
求问 — 记忆工具
===============

提供两个 Agent 工具：
  save_memory:   将重要信息保存到长期记忆（Chroma 向量库）
  recall_memory: 从长期记忆中搜索相关信息

使用场景：
  - 用户说"记住这个：飞书文档在 docs.feishu.cn" → save_memory
  - 用户问"我之前存的那个链接是什么" → recall_memory

注意：
  - 记忆持久化在 Chroma 容器的 volume 中，重启不丢失
  - 记忆与文档索引共享同一个 "docs" 集合，通过 metadata.source 区分
"""

import json
from dataclasses import dataclass


@dataclass
class SaveMemoryTool:
    """
    保存长期记忆工具。

    用途：Agent 判断用户提供的信息值得长期记住时调用。
    """

    name: str = "save_memory"
    description: str = "将重要信息保存到长期记忆中，以便将来回忆。当用户要求记住某些内容时调用。"
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "记忆的唯一标识符，简短描述（如 'feishu_doc_url'）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要保存的内容",
                    },
                },
                "required": ["key", "content"],
            },
        }

    async def execute(self, key: str, content: str, long_term_memory=None) -> str:
        """
        保存记忆到 Chroma。

        Args:
            key: 记忆标识符
            content: 记忆内容
            long_term_memory: LongTermMemory 实例（由 Agent 注入）

        Returns:
            JSON: {"status": "saved", "key": "..."}
        """
        if not long_term_memory:
            return json.dumps({"error": "记忆系统未初始化"})

        await long_term_memory.save_memory(key=key, content=content)
        return json.dumps({"status": "saved", "key": key}, ensure_ascii=False)


@dataclass
class RecallMemoryTool:
    """
    回忆长期记忆工具。

    用途：Agent 需要查找用户之前保存的信息时调用。
    """

    name: str = "recall_memory"
    description: str = "从长期记忆中搜索相关信息。当用户问到之前保存过的信息时调用。"
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询，描述要回忆的内容",
                    },
                },
                "required": ["query"],
            },
        }

    async def execute(self, query: str, long_term_memory=None) -> str:
        """
        从 Chroma 检索记忆。

        Args:
            query: 搜索查询
            long_term_memory: LongTermMemory 实例（由 Agent 注入）

        Returns:
            JSON: {"results": [{"text": "..."}, ...]}
        """
        if not long_term_memory:
            return json.dumps({"results": [], "message": "记忆系统未初始化"})

        results = await long_term_memory.recall_memory(query)
        return json.dumps(
            {"results": [{"text": r["text"]} for r in results]},
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# 工具实例（单例）
# ---------------------------------------------------------------------------
save_memory_tool = SaveMemoryTool()
recall_memory_tool = RecallMemoryTool()
