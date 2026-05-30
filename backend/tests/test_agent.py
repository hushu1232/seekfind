"""
求问 — Agent 引擎测试
=====================

测试 QiuWenAgent：
  - classify_intent 意图分类
  - _get_active_llm 模型选择
  - _extract_highlight_commands 高亮指令解析
  - record_feedback 反馈记录

注意：
  Agent 的 stream_reply 方法需要真实的 LLM 连接，
  这里只测试不依赖 LLM 的辅助方法。
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent import QiuWenAgent


class TestAgentIntentClassification:
    """意图分类测试。"""

    @pytest.mark.asyncio
    async def test_classify_doc_question(self):
        """文档问题应分类为 doc_question。"""
        agent = QiuWenAgent()
        agent._llm = MagicMock()
        agent._llm.ainvoke = AsyncMock(return_value=MagicMock(content="doc_question"))

        intent = await agent.classify_intent("怎么创建项目？")
        assert intent == "doc_question"

    @pytest.mark.asyncio
    async def test_classify_guide_request(self):
        """引导请求应分类为 guide_request。"""
        agent = QiuWenAgent()
        agent._llm = MagicMock()
        agent._llm.ainvoke = AsyncMock(return_value=MagicMock(content="guide_request"))

        intent = await agent.classify_intent("在哪里新建项目？")
        assert intent == "guide_request"

    @pytest.mark.asyncio
    async def test_classify_chat(self):
        """闲聊应分类为 chat。"""
        agent = QiuWenAgent()
        agent._llm = MagicMock()
        agent._llm.ainvoke = AsyncMock(return_value=MagicMock(content="chat"))

        intent = await agent.classify_intent("你好")
        assert intent == "chat"

    @pytest.mark.asyncio
    async def test_classify_invalid_returns_doc_question(self):
        """无效意图默认为 doc_question。"""
        agent = QiuWenAgent()
        agent._llm = MagicMock()
        agent._llm.ainvoke = AsyncMock(return_value=MagicMock(content="invalid_intent"))

        intent = await agent.classify_intent("测试")
        assert intent == "doc_question"


class TestAgentModelSelection:
    """模型选择（降级策略）测试。"""

    def test_local_model_default(self):
        """默认使用本地模型。"""
        agent = QiuWenAgent()
        agent._llm = "local_model"
        agent._cloud_llm = "cloud_model"
        agent._consecutive_failures = 0

        with patch("agent.settings") as mock_settings:
            mock_settings.model_strategy = "hybrid"
            mock_settings.fallback_threshold = 3
            assert agent._get_active_llm() == "local_model"

    def test_cloud_fallback(self):
        """连续失败后降级到云端。"""
        agent = QiuWenAgent()
        agent._llm = "local_model"
        agent._cloud_llm = "cloud_model"
        agent._consecutive_failures = 3

        with patch("agent.settings") as mock_settings:
            mock_settings.model_strategy = "hybrid"
            mock_settings.fallback_threshold = 3
            assert agent._get_active_llm() == "cloud_model"

    def test_cloud_only_mode(self):
        """CLOUD 模式直接使用云端。"""
        agent = QiuWenAgent()
        agent._llm = "local_model"
        agent._cloud_llm = "cloud_model"

        with patch("agent.settings") as mock_settings:
            mock_settings.model_strategy = "cloud"
            mock_settings.fallback_threshold = 3
            assert agent._get_active_llm() == "cloud_model"


class TestHighlightCommandExtraction:
    """高亮指令解析测试。"""

    @pytest.mark.asyncio
    async def test_extract_from_json_response(self):
        """从 JSON 格式回复中提取高亮指令。"""
        agent = QiuWenAgent()
        response = '''
        这是操作步骤：
        {
            "steps": [
                {"order": 1, "description": "点击新建按钮", "selector": "#new-btn"},
                {"order": 2, "description": "输入名称", "selector": "#name-input"}
            ],
            "summary": "完成创建"
        }
        '''

        commands = [c async for c in agent._process_guide_steps(response)]
        assert len(commands) == 2
        assert commands[0]["type"] == "highlight"
        assert commands[0]["selector"] == "#new-btn"
        assert commands[1]["selector"] == "#name-input"

    @pytest.mark.asyncio
    async def test_extract_no_json(self):
        """无 JSON 时返回空。"""
        agent = QiuWenAgent()
        response = "这是一段普通文本回复。"
        commands = [c async for c in agent._process_guide_steps(response)]
        assert len(commands) == 0

    @pytest.mark.asyncio
    async def test_extract_invalid_json(self):
        """无效 JSON 时返回空。"""
        agent = QiuWenAgent()
        response = "这不是有效的 JSON {broken"
        commands = [c async for c in agent._process_guide_steps(response)]
        assert len(commands) == 0


class TestFeedbackRecording:
    """反馈记录测试。"""

    @pytest.mark.asyncio
    async def test_record_feedback(self):
        """反馈应被记录到长期记忆。"""
        agent = QiuWenAgent()
        agent._long_term = AsyncMock()
        agent._long_term.save_memory = AsyncMock()

        feedback = {"step_id": "1", "is_correct": True}
        await agent.record_feedback(feedback)

        agent._long_term.save_memory.assert_called_once()
        call_args = agent._long_term.save_memory.call_args
        assert "feedback_1" in call_args.kwargs.get("key", call_args[1].get("key", ""))
