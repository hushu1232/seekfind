"""
Token 计数与上下文管理测试
"""

import pytest
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from utils.token_counter import TokenManager


class TestTokenManager:
    """TokenManager 测试。"""

    def test_count_chinese_tokens(self):
        """中文 token 估算。"""
        tm = TokenManager()
        # 中文约 1.5 字符/token
        tokens = tm.count_tokens("你好世界")
        assert 2 <= tokens <= 4

    def test_count_english_tokens(self):
        """英文 token 估算。"""
        tm = TokenManager()
        # 英文约 4 字符/token
        tokens = tm.count_tokens("hello world")
        assert 2 <= tokens <= 4

    def test_count_mixed_tokens(self):
        """中英混合 token 估算。"""
        tm = TokenManager()
        tokens = tm.count_tokens("GitHub 怎么创建 PR？")
        assert tokens > 0

    def test_count_empty(self):
        """空文本返回 0。"""
        tm = TokenManager()
        assert tm.count_tokens("") == 0

    def test_count_message_tokens(self):
        """单条消息 token 计数。"""
        tm = TokenManager()
        msg = HumanMessage(content="你好")
        tokens = tm.count_message_tokens(msg)
        assert tokens > 0

    def test_count_messages_tokens(self):
        """消息列表 token 计数。"""
        tm = TokenManager()
        messages = [
            SystemMessage(content="你是助手"),
            HumanMessage(content="你好"),
            AIMessage(content="你好！"),
        ]
        total = tm.count_messages_tokens(messages)
        assert total > 0

    def test_trim_no_needed(self):
        """未超限时不截断。"""
        tm = TokenManager(max_tokens=10000)
        messages = [
            SystemMessage(content="系统"),
            HumanMessage(content="你好"),
        ]
        result = tm.trim_messages(messages)
        assert len(result) == 2

    def test_trim_preserves_system(self):
        """截断时保留 system prompt。"""
        tm = TokenManager(max_tokens=20)
        messages = [
            SystemMessage(content="系统提示词"),
            HumanMessage(content="第一条消息很长很长很长很长很长"),
            AIMessage(content="回复很长很长很长很长很长"),
            HumanMessage(content="第二条消息很长很长很长很长很长"),
            AIMessage(content="回复很长很长很长很长很长"),
            HumanMessage(content="最新消息"),
        ]
        result = tm.trim_messages(messages)
        # system prompt 应该保留
        assert result[0].type == "system"
        # 最新消息应该保留
        assert result[-1].content == "最新消息"
        # 总数应该减少
        assert len(result) < len(messages)

    def test_trim_preserves_latest_user(self):
        """截断时保留最新 user 消息。"""
        tm = TokenManager(max_tokens=30)
        messages = [
            SystemMessage(content="系统"),
            HumanMessage(content="旧消息很长很长很长很长很长很长"),
            AIMessage(content="旧回复很长很长很长很长很长很长"),
            HumanMessage(content="新消息"),
        ]
        result = tm.trim_messages(messages)
        # 最后一条应该是新消息
        assert result[-1].content == "新消息"

    def test_custom_max_tokens(self):
        """自定义 max_tokens。"""
        tm = TokenManager(max_tokens=100)
        assert tm.max_tokens == 100
