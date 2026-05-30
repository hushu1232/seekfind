"""
求问 — 记忆工具
save_memory: 保存长期记忆
recall_memory: 回忆长期记忆
"""

import json
from dataclasses import dataclass


@dataclass
class SaveMemoryTool:
    """保存长期记忆。"""

    name: str = "save_memory"
    description: str = "将重要信息保存到长期记忆中，以便将来回忆。"
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
                        "description": "记忆的唯一标识符",
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
        """保存记忆。"""
        if not long_term_memory:
            return json.dumps({"error": "记忆系统未初始化"})
        await long_term_memory.save_memory(key=key, content=content)
        return json.dumps({"status": "saved", "key": key})


@dataclass
class RecallMemoryTool:
    """回忆长期记忆。"""

    name: str = "recall_memory"
    description: str = "从长期记忆中搜索相关信息。"
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
                        "description": "搜索查询",
                    },
                },
                "required": ["query"],
            },
        }

    async def execute(self, query: str, long_term_memory=None) -> str:
        """回忆记忆。"""
        if not long_term_memory:
            return json.dumps({"results": [], "message": "记忆系统未初始化"})
        results = await long_term_memory.recall_memory(query)
        return json.dumps(
            {"results": [{"text": r["text"]} for r in results]}, ensure_ascii=False
        )


save_memory_tool = SaveMemoryTool()
recall_memory_tool = RecallMemoryTool()
