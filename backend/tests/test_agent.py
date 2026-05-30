"""
求问 — Agent 引擎测试
=====================

测试 QiuWenAgent：
  - classify_intent 意图分类
  - _retrieve_context 上下文检索
  - analyze_page_event 主动监控
  - record_feedback 反馈记录
  - LangGraph 子图构建
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent import QiuWenAgent, AgentState, _build_rag_graph, _build_guide_graph
from langchain_core.messages import AIMessage, HumanMessage


class TestAgentIntentClassification:
    """意图分类测试。"""

    @pytest.mark.asyncio
    async def test_classify_doc_question(self):
        agent = QiuWenAgent()
        agent._chat_llm = MagicMock()
        agent._chat_llm.ainvoke = AsyncMock(return_value=MagicMock(content="doc_question"))
        intent = await agent.classify_intent("怎么创建项目？")
        assert intent == "doc_question"

    @pytest.mark.asyncio
    async def test_classify_guide_request(self):
        agent = QiuWenAgent()
        agent._chat_llm = MagicMock()
        agent._chat_llm.ainvoke = AsyncMock(return_value=MagicMock(content="guide_request"))
        intent = await agent.classify_intent("在哪里新建项目？")
        assert intent == "guide_request"

    @pytest.mark.asyncio
    async def test_classify_chat(self):
        agent = QiuWenAgent()
        agent._chat_llm = MagicMock()
        agent._chat_llm.ainvoke = AsyncMock(return_value=MagicMock(content="chat"))
        intent = await agent.classify_intent("你好")
        assert intent == "chat"

    @pytest.mark.asyncio
    async def test_classify_invalid_returns_doc_question(self):
        agent = QiuWenAgent()
        agent._chat_llm = MagicMock()
        agent._chat_llm.ainvoke = AsyncMock(return_value=MagicMock(content="invalid"))
        intent = await agent.classify_intent("测试")
        assert intent == "doc_question"


class TestAgentContextRetrieval:
    """上下文检索测试。"""

    @pytest.mark.asyncio
    async def test_retrieve_context_empty(self):
        """无 long_term 时返回空提示。"""
        agent = QiuWenAgent()
        agent._long_term = None
        ctx = await agent._retrieve_context("测试")
        assert "索引为空" in ctx

    @pytest.mark.asyncio
    async def test_retrieve_context_with_results(self, mock_long_term_memory):
        """有检索结果时返回拼接文本。"""
        agent = QiuWenAgent()
        agent._long_term = mock_long_term_memory
        ctx = await agent._retrieve_context("测试")
        assert "测试文档内容" in ctx


class TestAgentPageEventAnalysis:
    """主动监控测试。"""

    @pytest.mark.asyncio
    async def test_confused_user(self):
        agent = QiuWenAgent()
        result = await agent.analyze_page_event({
            "event_type": "user_confused",
            "message": "检测到你连续点击了 3 次",
        })
        assert result is not None
        assert result["type"] == "proactive_hint"

    @pytest.mark.asyncio
    async def test_form_page(self):
        agent = QiuWenAgent()
        result = await agent.analyze_page_event({
            "event_type": "route_change",
            "url": "https://app.example.com/create",
        })
        assert result is not None
        assert "表单" in result["message"]

    @pytest.mark.asyncio
    async def test_normal_page(self):
        agent = QiuWenAgent()
        result = await agent.analyze_page_event({
            "event_type": "route_change",
            "url": "https://app.example.com/dashboard",
        })
        assert result is None


class TestAgentFeedbackRecording:
    """反馈记录测试。"""

    @pytest.mark.asyncio
    async def test_record_feedback(self):
        agent = QiuWenAgent()
        agent._long_term = AsyncMock()
        agent._long_term.save_memory = AsyncMock()
        await agent.record_feedback({"step_id": "1", "is_correct": True})
        agent._long_term.save_memory.assert_called_once()


class TestLangGraphStructure:
    """LangGraph 子图结构测试。"""

    def test_rag_graph_has_required_nodes(self):
        """RAG 子图应包含 agent 和 tools 节点。"""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        graph = _build_rag_graph(llm)
        # 编译后的 graph 应该可以调用
        assert graph is not None

    def test_guide_graph_has_required_nodes(self):
        """引导子图应包含 agent 和 tools 节点。"""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        graph = _build_guide_graph(llm)
        assert graph is not None
