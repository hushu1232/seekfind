"""
求问 — 短期记忆（对话上下文管理）
维护单次会话的对话历史，最多保留 max_turns 轮。
"""

from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage


@dataclass
class ShortTermMemory:
    """短期对话记忆。"""

    max_turns: int = 50
    _messages: list[dict[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str):
        """添加一条消息。role: 'user' | 'assistant'"""
        self._messages.append({"role": role, "content": content})
        # 超出上限时裁剪（保留最近的 max_turns 轮）
        if len(self._messages) > self.max_turns * 2:
            self._messages = self._messages[-(self.max_turns * 2) :]

    def get(self) -> list[dict[str, str]]:
        """获取完整对话历史。"""
        return list(self._messages)

    def clear(self):
        """清空对话历史。"""
        self._messages.clear()

    def to_langchain_messages(self) -> list[BaseMessage]:
        """转换为 LangChain 消息格式。"""
        result = []
        for msg in self._messages:
            if msg["role"] == "user":
                result.append(HumanMessage(content=msg["content"]))
            else:
                result.append(AIMessage(content=msg["content"]))
        return result

    def to_dict(self) -> dict:
        """序列化为字典（用于持久化）。"""
        return {"max_turns": self.max_turns, "messages": list(self._messages)}

    @classmethod
    def from_dict(cls, data: dict) -> "ShortTermMemory":
        """从字典反序列化。"""
        mem = cls(max_turns=data.get("max_turns", 50))
        mem._messages = data.get("messages", [])
        return mem
