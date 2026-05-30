"""
求问 — 短期记忆模块
===================

职责：
  - 维护单次 WebSocket 会话的对话上下文
  - 自动裁剪超出 max_turns 的旧消息
  - 支持序列化/反序列化（用于 Chrome Storage 持久化）
  - 转换为 LangChain 消息格式供 Agent 使用

数据结构：
  _messages: [
    {"role": "user",      "content": "怎么创建项目"},
    {"role": "assistant", "content": "1. 点击..."},
    ...
  ]

线程安全：
  每个 WS 连接拥有独立的 ShortTermMemory 实例，无需加锁。
"""

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


@dataclass
class ShortTermMemory:
    """
    短期对话记忆。

    Attributes:
        max_turns: 最大保留轮数（每轮 = 1 条 user + 1 条 assistant）
        _messages: 内部消息列表，格式为 {"role": "user"|"assistant", "content": "..."}
    """

    max_turns: int = 50
    _messages: list[dict[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        """
        添加一条消息到对话历史。

        Args:
            role: "user" 或 "assistant"
            content: 消息文本

        自动裁剪：
          当消息数超过 max_turns * 2 时，保留最近的消息，
          确保对话上下文不超过 LLM 的上下文窗口。
        """
        self._messages.append({"role": role, "content": content})
        # 裁剪策略：保留最近 max_turns 轮（每轮 2 条消息）
        if len(self._messages) > self.max_turns * 2:
            self._messages = self._messages[-(self.max_turns * 2) :]

    def get(self) -> list[dict[str, str]]:
        """获取完整对话历史（返回副本，防止外部修改）。"""
        return list(self._messages)

    def clear(self) -> None:
        """清空对话历史（用户手动清除或会话重建时调用）。"""
        self._messages.clear()

    def to_langchain_messages(self) -> list[BaseMessage]:
        """
        转换为 LangChain 消息格式。

        用途：直接传入 LLM 的 messages 参数。
        映射：user → HumanMessage, assistant → AIMessage
        """
        result: list[BaseMessage] = []
        for msg in self._messages:
            if msg["role"] == "user":
                result.append(HumanMessage(content=msg["content"]))
            else:
                result.append(AIMessage(content=msg["content"]))
        return result

    def to_dict(self) -> dict:
        """
        序列化为字典。

        用途：
          - Chrome Storage 持久化（service_worker.ts 中调用）
          - 跨页面状态恢复
        """
        return {"max_turns": self.max_turns, "messages": list(self._messages)}

    @classmethod
    def from_dict(cls, data: dict) -> "ShortTermMemory":
        """
        从字典反序列化。

        用途：
          - Service Worker 启动时从 Chrome Storage 恢复
          - 断线重连后恢复对话上下文
        """
        mem = cls(max_turns=data.get("max_turns", 50))
        mem._messages = data.get("messages", [])
        return mem
