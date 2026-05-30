"""
求问 — 工具集测试
=================

测试所有工具的：
  - schema 格式正确
  - execute 方法返回预期结果
  - 边界条件处理
"""

import json
import pytest

from tools.search_docs import SearchDocsTool
from tools.fetch_doc_page import FetchDocPageTool
from tools.memory_tools import SaveMemoryTool, RecallMemoryTool
from tools.highlight_element import HighlightElementTool
from tools.classify_page import ClassifyPageTool
from tools.learn_flow import LearnFlowTool


class TestSearchDocsTool:
    """SearchDocsTool 测试。"""

    def test_schema_format(self):
        """schema 格式符合 OpenAI Function Calling 规范。"""
        tool = SearchDocsTool()
        assert tool.name == "search_docs"
        assert "parameters" in tool.schema
        assert "query" in tool.schema["parameters"]["properties"]
        assert "query" in tool.schema["parameters"]["required"]

    @pytest.mark.asyncio
    async def test_execute_no_memory(self):
        """无 long_term_memory 时返回空结果。"""
        tool = SearchDocsTool()
        result = await tool.execute("测试查询")
        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_execute_with_mock_memory(self, mock_long_term_memory):
        """有 mock memory 时返回结果。"""
        tool = SearchDocsTool()
        result = await tool.execute("测试查询", long_term_memory=mock_long_term_memory)
        data = json.loads(result)
        assert len(data["results"]) > 0


class TestFetchDocPageTool:
    """FetchDocPageTool 测试。"""

    def test_schema_format(self):
        tool = FetchDocPageTool()
        assert tool.name == "fetch_doc_page"
        assert "url" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_invalid_url(self):
        """无效 URL 返回错误。"""
        tool = FetchDocPageTool()
        result = await tool.execute("not-a-valid-url")
        data = json.loads(result)
        assert "error" in data


class TestMemoryTools:
    """MemoryTools 测试。"""

    def test_save_memory_schema(self):
        tool = SaveMemoryTool()
        assert tool.name == "save_memory"
        assert "key" in tool.schema["parameters"]["properties"]
        assert "content" in tool.schema["parameters"]["properties"]

    def test_recall_memory_schema(self):
        tool = RecallMemoryTool()
        assert tool.name == "recall_memory"
        assert "query" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_save_memory_no_system(self):
        """无记忆系统时返回错误。"""
        tool = SaveMemoryTool()
        result = await tool.execute("key", "content")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_recall_memory_no_system(self):
        tool = RecallMemoryTool()
        result = await tool.execute("query")
        data = json.loads(result)
        assert data["results"] == []


class TestHighlightElementTool:
    """HighlightElementTool 测试。"""

    def test_schema_format(self):
        tool = HighlightElementTool()
        assert tool.name == "highlight_element"
        assert "selector" in tool.schema["parameters"]["properties"]
        assert "description" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_returns_highlight_command(self):
        tool = HighlightElementTool()
        result = await tool.execute("#test-btn", "测试按钮")
        data = json.loads(result)
        assert data["action"] == "highlight"
        assert data["selector"] == "#test-btn"
        assert data["description"] == "测试按钮"


class TestClassifyPageTool:
    """ClassifyPageTool 测试。"""

    def test_schema_format(self):
        tool = ClassifyPageTool()
        assert tool.name == "classify_page"
        assert "url" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_classify_dashboard_url(self):
        """dashboard URL 应被分类为 dashboard。"""
        tool = ClassifyPageTool()
        result = await tool.execute("https://app.example.com/dashboard")
        data = json.loads(result)
        assert data["page_type"] == "dashboard"
        assert data["method"] == "rule"

    @pytest.mark.asyncio
    async def test_classify_login_url(self):
        """login URL 应被分类为 form。"""
        tool = ClassifyPageTool()
        result = await tool.execute("https://app.example.com/login")
        data = json.loads(result)
        assert data["page_type"] == "form"

    @pytest.mark.asyncio
    async def test_classify_unknown_url(self):
        """未知 URL 返回 other。"""
        tool = ClassifyPageTool()
        result = await tool.execute("https://example.com/random")
        data = json.loads(result)
        assert data["page_type"] == "other"


class TestLearnFlowTool:
    """LearnFlowTool 测试。"""

    def test_schema_format(self):
        tool = LearnFlowTool()
        assert tool.name == "learn_flow"
        assert "action" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_start_recording(self):
        tool = LearnFlowTool()
        result = await tool.execute("start_recording", "测试流程")
        data = json.loads(result)
        assert data["status"] == "recording"
        assert tool._is_recording is True

    @pytest.mark.asyncio
    async def test_stop_recording(self):
        tool = LearnFlowTool()
        await tool.execute("start_recording", "测试流程")
        result = await tool.execute("stop_recording")
        data = json.loads(result)
        assert data["status"] == "saved"
        assert tool._is_recording is False

    @pytest.mark.asyncio
    async def test_start_without_name(self):
        tool = LearnFlowTool()
        result = await tool.execute("start_recording")
        data = json.loads(result)
        assert "error" in data

    def test_add_step(self):
        tool = LearnFlowTool()
        tool._is_recording = True
        tool.add_step("click", "#btn", "点击按钮")
        assert len(tool._current_steps) == 1
        assert tool._current_steps[0]["action"] == "click"

    def test_add_step_not_recording(self):
        tool = LearnFlowTool()
        tool.add_step("click", "#btn", "点击按钮")
        assert len(tool._current_steps) == 0
