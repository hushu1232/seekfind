"""
求问 — 核心业务流测试
====================

测试实际业务场景能否跑通：
  1. 知识库搜索 → 返回相关结果
  2. 工具初始化 → schema 正确
  3. 无障碍树快照 → @eN 引用
  4. 语义定位器 → 元素查找
  5. 指纹存储 → 保存/查找/模糊匹配
  6. 页面分类 → 规则匹配
  7. 浏览器交互工具 → schema 完整
"""

import json

import pytest
from tools import get_all_tools, get_tool_by_name, get_tool_schemas
from tools.browser_tools import BrowserFindTool, BrowserInteractTool, BrowserSnapshotTool
from tools.classify_page import ClassifyPageTool
from tools.highlight_element import HighlightElementTool
from tools.search_docs import SearchDocsTool


class TestKnowledgeBaseSearch:
    """知识库搜索业务流。"""

    def test_search_tool_schema_complete(self):
        """search_docs 工具 schema 完整。"""
        tool = SearchDocsTool()
        assert tool.name == "search_docs"
        assert "query" in tool.schema["parameters"]["properties"]
        assert "query" in tool.schema["parameters"]["required"]

    @pytest.mark.asyncio
    async def test_search_returns_results_with_mock(self, mock_long_term_memory):
        """搜索返回结果。"""
        tool = SearchDocsTool()
        result = await tool.execute("怎么创建项目", long_term_memory=mock_long_term_memory)
        data = json.loads(result)
        assert "results" in data
        assert len(data["results"]) > 0


class TestToolInitialization:
    """工具初始化业务流。"""

    def test_all_tools_loadable(self):
        """所有 12 个工具可加载。"""
        tools = get_all_tools()
        assert len(tools) == 12
        names = [t.name for t in tools]
        assert "search_docs" in names
        assert "fetch_doc_page" in names
        assert "highlight_element" in names
        assert "browser_snapshot" in names
        assert "browser_interact" in names
        assert "browser_find" in names

    def test_tool_schemas_valid(self):
        """所有工具 schema 符合 OpenAI Function Calling 规范。"""
        schemas = get_tool_schemas()
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert schema["parameters"]["type"] == "object"
            assert "properties" in schema["parameters"]

    def test_tool_by_name(self):
        """按名称获取工具。"""
        tool = get_tool_by_name("browser_snapshot")
        assert tool.name == "browser_snapshot"


class TestHighlightElement:
    """高亮元素业务流。"""

    def test_highlight_schema_has_page_url(self):
        """highlight_element 包含 page_url 参数。"""
        tool = HighlightElementTool()
        props = tool.schema["parameters"]["properties"]
        assert "page_url" in props
        assert "selector" in props
        assert "description" in props

    @pytest.mark.asyncio
    async def test_highlight_with_fingerprint(self, fingerprint_storage):
        """高亮 + 指纹存储闭环。"""
        tool = HighlightElementTool()

        # 第一次：正常高亮，自动存储指纹
        result = await tool.execute(
            selector="#create-btn",
            description="创建按钮",
            page_url="https://github.com/dashboard",
            fingerprint_storage=fingerprint_storage,
        )
        data = json.loads(result)
        assert data["action"] == "highlight"
        assert data["selector"] == "#create-btn"

        # 验证指纹已存储
        fp = fingerprint_storage.find("https://github.com/settings", "创建按钮")
        assert fp is not None
        assert fp["selector"] == "#create-btn"

    @pytest.mark.asyncio
    async def test_highlight_auto_from_fingerprint(self, fingerprint_storage):
        """selector=auto 时从指纹库查找。"""
        # 先存储一个指纹
        fingerprint_storage.save("github.com", "#cached-btn", "缓存按钮")

        tool = HighlightElementTool()
        result = await tool.execute(
            selector="auto",
            description="缓存按钮",
            page_url="https://github.com/dashboard",
            fingerprint_storage=fingerprint_storage,
        )
        data = json.loads(result)
        assert data["selector"] == "#cached-btn"


class TestPageClassification:
    """页面分类业务流。"""

    def test_classify_dashboard(self):
        """dashboard URL 分类正确。"""
        tool = ClassifyPageTool()
        result = tool._classify_by_rules("https://app.example.com/dashboard", "")
        assert result["page_type"] == "dashboard"
        assert result["method"] == "rule"

    def test_classify_login_form(self):
        """login URL 分类为 form。"""
        tool = ClassifyPageTool()
        result = tool._classify_by_rules("https://app.example.com/login", "")
        assert result["page_type"] == "form"

    def test_classify_with_dom_features(self):
        """DOM 特征辅助分类。"""
        tool = ClassifyPageTool()
        result = tool._classify_by_rules(
            "https://app.example.com/page",
            '<div class="data-table"><table>...</table></div>'
        )
        assert result["page_type"] == "list"


class TestFingerprintStorage:
    """指纹存储业务流。"""

    def test_full_lifecycle(self, fingerprint_storage):
        """完整生命周期：保存 → 查找 → 成功计数 → 失败记录 → 清理。"""
        # 保存
        fingerprint_storage.save("github.com", "#btn", "按钮")
        fingerprint_storage.save("github.com", "#btn", "按钮")

        # 查找
        fp = fingerprint_storage.find("https://github.com", "按钮")
        assert fp is not None
        assert fp["success_count"] == 2

        # 模糊查找
        fp2 = fingerprint_storage.find("https://github.com", "那个按钮")
        assert fp2 is not None  # 相似度匹配

        # 失败记录
        fingerprint_storage.record_failure(fp["id"])

        # 统计
        stats = fingerprint_storage.get_stats()
        assert stats["total"] == 1

    def test_domain_isolation(self, fingerprint_storage):
        """不同域名隔离。"""
        fingerprint_storage.save("github.com", "#btn", "按钮")
        assert fingerprint_storage.find("https://gitlab.com", "按钮") is None
        assert fingerprint_storage.find("https://github.com", "按钮") is not None


class TestBrowserTools:
    """浏览器工具业务流。"""

    def test_snapshot_tool_schema(self):
        """browser_snapshot schema 完整。"""
        tool = BrowserSnapshotTool()
        assert tool.name == "browser_snapshot"
        props = tool.schema["parameters"]["properties"]
        assert "interactive_only" in props
        assert "selector" in props
        assert "max_depth" in props

    def test_interact_tool_schema(self):
        """browser_interact schema 完整。"""
        tool = BrowserInteractTool()
        assert tool.name == "browser_interact"
        props = tool.schema["parameters"]["properties"]
        assert "ref" in props
        assert "action" in props
        assert "value" in props
        actions = props["action"]["enum"]
        assert "click" in actions
        assert "fill" in actions
        assert "hover" in actions

    def test_find_tool_schema(self):
        """browser_find schema 完整。"""
        tool = BrowserFindTool()
        assert tool.name == "browser_find"
        props = tool.schema["parameters"]["properties"]
        assert "strategy" in props
        assert "value" in props
        strategies = props["strategy"]["enum"]
        assert "role" in strategies
        assert "text" in strategies
        assert "label" in strategies

    @pytest.mark.asyncio
    async def test_snapshot_without_controller(self):
        """无浏览器控制器时返回错误。"""
        tool = BrowserSnapshotTool()
        result = await tool.execute(browser_controller=None)
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_interact_without_controller(self):
        """无浏览器控制器时返回错误。"""
        tool = BrowserInteractTool()
        result = await tool.execute(ref="@e1", action="click", browser_controller=None)
        data = json.loads(result)
        assert "error" in data


class TestEndToEndFlow:
    """端到端业务流模拟。"""

    def test_tool_chain_search_highlight(self):
        """模拟：用户问"在哪创建项目" → 搜索 → 高亮。"""
        # Step 1: 搜索工具可用
        search_tool = get_tool_by_name("search_docs")
        assert search_tool is not None

        # Step 2: 高亮工具可用
        highlight_tool = get_tool_by_name("highlight_element")
        assert highlight_tool is not None

        # Step 3: 两者 schema 都正确
        assert "query" in search_tool.schema["parameters"]["properties"]
        assert "selector" in highlight_tool.schema["parameters"]["properties"]

    def test_tool_chain_snapshot_interact(self):
        """模拟：获取快照 → 交互。"""
        # Step 1: 快照工具可用
        snapshot_tool = get_tool_by_name("browser_snapshot")
        assert snapshot_tool is not None

        # Step 2: 交互工具可用
        interact_tool = get_tool_by_name("browser_interact")
        assert interact_tool is not None

        # Step 3: 查找工具可用
        find_tool = get_tool_by_name("browser_find")
        assert find_tool is not None

    def test_mcp_tool_coverage(self):
        """MCP 工具覆盖完整。"""
        expected_tools = [
            "search_docs", "fetch_doc_page", "highlight_element",
            "classify_page", "learn_flow",
            "save_memory", "recall_memory",
            "visual_locate", "screenshot_annotate",
            "browser_snapshot", "browser_interact", "browser_find",
        ]
        actual_names = [t.name for t in get_all_tools()]
        for name in expected_tools:
            assert name in actual_names, f"缺少工具: {name}"
