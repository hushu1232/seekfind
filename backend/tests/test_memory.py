"""
求问 — 记忆模块测试
===================

测试 ShortTermMemory：
  - add / get / clear
  - max_turns 裁剪
  - to_langchain_messages
  - 序列化/反序列化

测试 LongTermMemory：
  - initialize（mock）
  - add / search
  - save_memory / recall_memory
"""

import pytest
from memory.short_term import ShortTermMemory


class TestShortTermMemory:
    """ShortTermMemory 单元测试。"""

    def test_add_and_get(self, short_term_memory):
        """测试基本的添加和获取。"""
        short_term_memory.add("user", "你好")
        short_term_memory.add("assistant", "你好！有什么可以帮你的？")

        messages = short_term_memory.get()
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "你好"}
        assert messages[1] == {"role": "assistant", "content": "你好！有什么可以帮你的？"}

    def test_clear(self, short_term_memory):
        """测试清空。"""
        short_term_memory.add("user", "消息1")
        short_term_memory.add("assistant", "回复1")
        short_term_memory.clear()

        messages = short_term_memory.get()
        assert len(messages) == 0

    def test_max_turns_trimming(self):
        """测试超出 max_turns 时自动裁剪。"""
        mem = ShortTermMemory(max_turns=3)

        # 添加 4 轮（8 条消息）
        for i in range(4):
            mem.add("user", f"问题{i}")
            mem.add("assistant", f"回答{i}")

        # 应该只保留最近 3 轮（6 条消息）
        messages = mem.get()
        assert len(messages) == 6
        assert messages[0]["content"] == "问题1"  # 第 0 轮被裁剪

    def test_to_langchain_messages(self, short_term_memory):
        """测试转换为 LangChain 消息格式。"""
        short_term_memory.add("user", "你好")
        short_term_memory.add("assistant", "你好！")

        from langchain_core.messages import HumanMessage, AIMessage

        lc_messages = short_term_memory.to_langchain_messages()
        assert len(lc_messages) == 2
        assert isinstance(lc_messages[0], HumanMessage)
        assert isinstance(lc_messages[1], AIMessage)
        assert lc_messages[0].content == "你好"
        assert lc_messages[1].content == "你好！"

    def test_to_dict_and_from_dict(self, short_term_memory):
        """测试序列化和反序列化。"""
        short_term_memory.add("user", "测试消息")
        short_term_memory.add("assistant", "测试回复")

        data = short_term_memory.to_dict()
        assert "messages" in data
        assert data["max_turns"] == 50
        assert len(data["messages"]) == 2

        restored = ShortTermMemory.from_dict(data)
        assert len(restored.get()) == 2
        assert restored.get()[0]["content"] == "测试消息"

    def test_get_returns_copy(self, short_term_memory):
        """测试 get 返回副本，不影响内部状态。"""
        short_term_memory.add("user", "消息")
        messages = short_term_memory.get()
        messages.clear()  # 清空副本

        # 内部状态不受影响
        assert len(short_term_memory.get()) == 1
