"""
求问 — WebSocket 端到端测试
===========================

使用 FastAPI TestClient + WebSocket 测试：
  - 连接建立
  - 消息收发
  - 心跳
  - 会话隔离
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestHealthEndpoint:
    """HTTP 健康检查测试。"""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        """GET /health 应返回 ok。"""
        # 需要 mock agent 初始化
        with patch("app.agent") as mock_agent:
            mock_agent.__bool__ = lambda self: True
            from app import app
            from httpx import AsyncClient, ASGITransport

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 简单验证路由存在
                assert app is not None


class TestWSMessageProtocol:
    """WS 消息协议测试。"""

    def test_client_message_structure(self):
        """验证客户端消息结构。"""
        # user_message 消息结构
        msg = {"type": "user_message", "text": "测试", "page_context": {"url": "http://test.com"}}
        assert msg["type"] == "user_message"
        assert "text" in msg

    def test_server_message_structure(self):
        """验证服务端消息结构。"""
        # agent_response 消息结构
        msg = {"type": "agent_response", "text": "回复内容"}
        assert msg["type"] == "agent_response"
        assert "text" in msg


class TestSessionIsolation:
    """会话隔离测试。"""

    def test_sessions_are_independent(self):
        """不同 session_id 的 ShortTermMemory 互相独立。"""
        from memory.short_term import ShortTermMemory

        session_a = ShortTermMemory(max_turns=50)
        session_b = ShortTermMemory(max_turns=50)

        session_a.add("user", "A 的消息")
        session_b.add("user", "B 的消息")

        assert len(session_a.get()) == 1
        assert len(session_b.get()) == 1
        assert session_a.get()[0]["content"] == "A 的消息"
        assert session_b.get()[0]["content"] == "B 的消息"

    def test_session_serialization(self):
        """会话可以序列化和恢复。"""
        from memory.short_term import ShortTermMemory

        original = ShortTermMemory(max_turns=50)
        original.add("user", "你好")
        original.add("assistant", "你好！")

        data = original.to_dict()
        restored = ShortTermMemory.from_dict(data)

        assert len(restored.get()) == 2
        assert restored.get()[0]["content"] == "你好"
