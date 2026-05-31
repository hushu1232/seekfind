"""
求问 — Token 计数与上下文管理
============================

功能：
  - 统计消息 token 数
  - 自动截断旧消息，保证不超限
  - 保留 system prompt + 最近对话

策略：
  - 优先保留 system prompt（始终在上下文开头）
  - 优先保留最近的对话（FIFO 截断旧消息）
  - 工具调用结果也计入 token
"""

import structlog
from langchain_core.messages import BaseMessage

logger = structlog.get_logger()


class TokenManager:
    """
    Token 计数与上下文管理。

    使用字符数估算 token（中文约 1.5 字符/token，英文约 4 字符/token）。
    比 tiktoken 更轻量，无需额外依赖。
    """

    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens

    def count_tokens(self, text: str) -> int:
        """
        估算文本 token 数。

        中文：约 1.5 字符/token
        英文：约 4 字符/token（按空格分词）
        """
        if not text:
            return 0

        # 统计中文字符
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        # 统计非中文字符
        other_chars = len(text) - chinese_chars

        # 估算
        chinese_tokens = chinese_chars / 1.5
        other_tokens = other_chars / 4.0

        return int(chinese_tokens + other_tokens) + 1  # +1 for overhead

    def count_message_tokens(self, message: BaseMessage) -> int:
        """统计单条消息的 token 数。"""
        content = message.content if isinstance(message.content, str) else str(message.content)
        return self.count_tokens(content)

    def count_messages_tokens(self, messages: list[BaseMessage]) -> int:
        """统计消息列表的总 token 数。"""
        return sum(self.count_message_tokens(m) for m in messages)

    def trim_messages(
        self,
        messages: list[BaseMessage],
        max_tokens: int | None = None,
        preserve_system: bool = True,
    ) -> list[BaseMessage]:
        """
        截断消息列表，保证总 token 不超限。

        策略：
          1. 保留 system prompt（第一条）
          2. 从最旧的消息开始删除
          3. 始终保留最新的 user 消息

        Args:
            messages: 消息列表
            max_tokens: 最大 token 数（默认使用 self.max_tokens）
            preserve_system: 是否保留 system prompt

        Returns:
            截断后的消息列表
        """
        limit = max_tokens or self.max_tokens
        total = self.count_messages_tokens(messages)

        if total <= limit:
            return messages

        # 保留 system prompt
        system_msgs = []
        other_msgs = []
        for msg in messages:
            if preserve_system and msg.type == "system":
                system_msgs.append(msg)
            else:
                other_msgs.append(msg)

        system_tokens = self.count_messages_tokens(system_msgs)
        remaining_budget = limit - system_tokens

        # 从最新的消息开始保留
        kept = []
        used_tokens = 0

        # 始终保留最后一条 user 消息
        if other_msgs:
            last_msg = other_msgs[-1]
            last_tokens = self.count_message_tokens(last_msg)
            kept = [last_msg]
            used_tokens = last_tokens
            other_msgs = other_msgs[:-1]

        # 从后往前添加消息
        for msg in reversed(other_msgs):
            msg_tokens = self.count_message_tokens(msg)
            if used_tokens + msg_tokens > remaining_budget:
                break
            kept.insert(0, msg)
            used_tokens += msg_tokens

        result = system_msgs + kept

        if len(result) < len(messages):
            logger.info(
                "上下文截断",
                original=len(messages),
                trimmed=len(result),
                original_tokens=total,
                trimmed_tokens=self.count_messages_tokens(result),
                max_tokens=limit,
            )

        return result


# 全局实例
_token_manager: TokenManager | None = None


def get_token_manager(max_tokens: int = 4096) -> TokenManager:
    """获取 TokenManager 单例。"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager(max_tokens)
    return _token_manager
