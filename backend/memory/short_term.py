"""
求问 — 短期记忆模块
===================

优化点：
  - 使用 collections.deque(maxlen) 替代 list，自动裁剪旧消息
  - O(1) 追加，无需手动检查长度
"""

from collections import deque
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


class ShortTermMemory:
    """
    短期对话记忆（deque 优化版）。

    使用 deque(maxlen) 自动裁剪旧消息，无需手动检查长度。
    """

    def __init__(self, max_turns: int = 50):
        self.max_turns = max_turns
        self._messages: deque[dict[str, str]] = deque(maxlen=max_turns * 2)

    def add(self, role: str, content: str) -> None:
        """添加消息。超出 maxlen 自动丢弃最旧的消息。"""
        self._messages.append({"role": role, "content": content})

    def get(self) -> list[dict[str, str]]:
        """获取完整对话历史。"""
        return list(self._messages)

    def clear(self) -> None:
        """清空对话历史。"""
        self._messages.clear()

    def to_langchain_messages(self) -> list[BaseMessage]:
        """转换为 LangChain 消息格式。"""
        result: list[BaseMessage] = []
        for msg in self._messages:
            if msg["role"] == "user":
                result.append(HumanMessage(content=msg["content"]))
            else:
                result.append(AIMessage(content=msg["content"]))
        return result

    def to_dict(self) -> dict:
        """序列化。"""
        return {"max_turns": self.max_turns, "messages": list(self._messages)}

    @classmethod
    def from_dict(cls, data: dict) -> "ShortTermMemory":
        """反序列化。"""
        mem = cls(max_turns=data.get("max_turns", 50))
        for msg in data.get("messages", []):
            mem._messages.append(msg)
        return mem
