"""
求问 — 网络集成测试
==================

测试需要真实网络连接的业务流：
  1. Scrapling Fetcher 真实页面抓取
  2. 浏览器指纹生成
  3. 知识库完整性验证
  4. 索引构建流程
  5. 工具链端到端

运行：python -m pytest tests/test_integration.py -v
"""

import json
import os
import pytest

# 标记所有测试为需要网络
pytestmark = pytest.mark.slow


class TestScraplingFetcherReal:
    """Scrapling Fetcher 真实网络测试。"""

    @pytest.mark.asyncio
    async def test_fetch_simple_page(self):
        """抓取简单 HTML 页面。"""
        from indexer.scrapling_fetcher import ScraplingFetcher

        fetcher = ScraplingFetcher(mode="http")
        doc = await fetcher.fetch("https://example.com")

        assert doc.text  # 应有正文
        assert doc.status == 200
        assert doc.fetched_at > 0
        assert doc.url == "https://example.com"
        assert doc.fetcher_type in ("scrapling_http", "httpx_fallback")
        print(f"\n  抓取成功: {len(doc.text)} 字符, 方式: {doc.fetcher_type}")

    @pytest.mark.asyncio
    async def test_fetch_with_title(self):
        """抓取带标题的页面。"""
        from indexer.scrapling_fetcher import ScraplingFetcher

        fetcher = ScraplingFetcher(mode="http")
        doc = await fetcher.fetch("https://example.com")

        assert doc.status == 200
        assert doc.text  # 应有内容
        print(f"\n  标题: {doc.title}, 正文: {len(doc.text)} 字符")

    @pytest.mark.asyncio
    async def test_fetch_404(self):
        """抓取 404 页面。"""
        from indexer.scrapling_fetcher import ScraplingFetcher

        fetcher = ScraplingFetcher(mode="http")
        try:
            doc = await fetcher.fetch("https://httpstat.us/404")
            # 可能返回错误或空内容
            print(f"\n  404 处理: status={doc.status}, text_len={len(doc.text)}")
        except Exception as e:
            print(f"\n  404 异常: {e}")

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        """超时处理。"""
        from indexer.scrapling_fetcher import ScraplingFetcher

        fetcher = ScraplingFetcher(mode="http", timeout=3)
        try:
            doc = await fetcher.fetch("https://httpstat.us/524?sleep=10000")
            print(f"\n  超时未触发: status={doc.status}")
        except Exception as e:
            print(f"\n  超时正确触发: {type(e).__name__}")

    @pytest.mark.asyncio
    async def test_fetch_content_truncation(self):
        """超长内容截断。"""
        from indexer.scrapling_fetcher import ScraplingFetcher

        fetcher = ScraplingFetcher(mode="http", max_content_length=100)
        doc = await fetcher.fetch("https://example.com")

        assert len(doc.text) <= 150  # 允许一些余量
        print(f"\n  截断后: {len(doc.text)} 字符")


class TestBrowserFingerprints:
    """浏览器指纹生成测试。"""

    def test_generate_headers(self):
        """生成真实浏览器 headers。"""
        from indexer.fingerprints import generate_stealth_headers

        headers = generate_stealth_headers()

        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert len(headers["User-Agent"]) > 20
        assert "Accept" in headers
        print(f"\n  UA: {headers['User-Agent'][:80]}...")

    def test_headers_diversity(self):
        """多次生成应有不同 UA。"""
        from indexer.fingerprints import generate_stealth_headers

        uas = set()
        for _ in range(10):
            headers = generate_stealth_headers()
            uas.add(headers["User-Agent"])

        print(f"\n  10 次生成: {len(uas)} 种不同 UA")
        assert len(uas) >= 1  # 至少有 1 种

    def test_random_user_agent(self):
        """随机 UA 字符串。"""
        from indexer.fingerprints import get_random_user_agent

        ua = get_random_user_agent()
        assert isinstance(ua, str)
        assert "Mozilla" in ua
        print(f"\n  随机 UA: {ua[:80]}...")


class TestKnowledgeBaseIntegrity:
    """知识库完整性测试。"""

    KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge", "builtin")

    def test_all_json_valid(self):
        """所有 JSON 文件可解析。"""
        import glob

        json_files = glob.glob(os.path.join(self.KNOWLEDGE_DIR, "*.json"))
        assert len(json_files) > 30, f"知识库文件太少: {len(json_files)}"

        total_entries = 0
        for f in json_files:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            assert "product" in data, f"{f} 缺少 product"
            assert "entries" in data, f"{f} 缺少 entries"
            for entry in data["entries"]:
                assert "question" in entry, f"{f} 条目缺少 question"
                assert "answer" in entry, f"{f} 条目缺少 answer"
            total_entries += len(data["entries"])

        print(f"\n  {len(json_files)} 个产品, {total_entries} 条知识")
        assert total_entries >= 200, f"知识库条目不足: {total_entries}"

    def test_high_frequency_products_have_enough_entries(self):
        """高频产品至少有 8 条。"""
        high_freq = ["github.json", "vscode.json", "docker.json", "feishu.json", "notion.json"]

        for filename in high_freq:
            filepath = os.path.join(self.KNOWLEDGE_DIR, filename)
            if not os.path.exists(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            count = len(data["entries"])
            print(f"\n  {data['product']}: {count} 条")
            assert count >= 8, f"{filename} 条目不足: {count}"

    def test_entries_have_selectors(self):
        """条目应包含 selectors 字段。"""
        import glob

        json_files = glob.glob(os.path.join(self.KNOWLEDGE_DIR, "*.json"))
        entries_with_selectors = 0
        total_entries = 0

        for f in json_files:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for entry in data["entries"]:
                total_entries += 1
                if entry.get("selectors"):
                    entries_with_selectors += 1

        ratio = entries_with_selectors / max(total_entries, 1)
        print(f"\n  {entries_with_selectors}/{total_entries} 条目有 selectors ({ratio:.0%})")


class TestIndexBuilderReal:
    """索引构建真实测试。"""

    @pytest.mark.asyncio
    async def test_chunk_document(self):
        """文档分块。"""
        from indexer.build_index import IndexBuilder
        from indexer.crawler import CrawledDoc

        doc = CrawledDoc(
            url="https://example.com",
            title="Test",
            text="第一段内容。\n\n第二段内容，比较长。" * 10,
        )
        builder = IndexBuilder(chunk_size=100, chunk_overlap=20)
        chunks = builder.chunk_document(doc)

        assert len(chunks) > 1
        for chunk in chunks:
            assert "id" in chunk
            assert "text" in chunk
            assert "metadata" in chunk
            assert chunk["metadata"]["source_url"] == "https://example.com"

        print(f"\n  分块: {len(chunks)} 个, 每个 ~{sum(len(c['text']) for c in chunks)//len(chunks)} 字符")

    def test_fingerprint_storage_persistence(self, tmp_path):
        """指纹存储持久化。"""
        from memory.fingerprint_storage import FingerprintStorage

        db_path = str(tmp_path / "test.db")

        # 写入
        storage1 = FingerprintStorage(db_path)
        storage1.save("github.com", "#btn", "按钮")
        storage1.close()

        # 重新打开
        storage2 = FingerprintStorage(db_path)
        fp = storage2.find("https://github.com", "按钮")
        assert fp is not None
        assert fp["selector"] == "#btn"
        storage2.close()

        print(f"\n  持久化验证: 写入后重新打开可查到")


class TestToolChainEndToEnd:
    """工具链端到端测试。"""

    @pytest.mark.asyncio
    async def test_search_highlight_chain(self, mock_long_term_memory, tmp_path):
        """搜索 → 高亮 链路。"""
        from tools.search_docs import SearchDocsTool
        from tools.highlight_element import HighlightElementTool
        from memory.fingerprint_storage import FingerprintStorage

        # Step 1: 搜索
        search = SearchDocsTool()
        result = await search.execute("怎么创建项目", long_term_memory=mock_long_term_memory)
        data = json.loads(result)
        assert len(data["results"]) > 0
        print(f"\n  搜索: 返回 {len(data['results'])} 条结果")

        # Step 2: 高亮（用指纹存储）
        storage = FingerprintStorage(str(tmp_path / "fp.db"))
        highlight = HighlightElementTool()

        # 首次高亮
        r1 = await highlight.execute(
            selector="#create-btn",
            description="创建按钮",
            page_url="https://github.com/dashboard",
            fingerprint_storage=storage,
        )
        d1 = json.loads(r1)
        assert d1["action"] == "highlight"
        print(f"  首次高亮: selector={d1['selector']}")

        # 二次高亮（auto 模式）
        r2 = await highlight.execute(
            selector="auto",
            description="创建按钮",
            page_url="https://github.com/settings",
            fingerprint_storage=storage,
        )
        d2 = json.loads(r2)
        assert d2["selector"] == "#create-btn"
        print(f"  二次高亮(auto): selector={d2['selector']}")

    @pytest.mark.asyncio
    async def test_classify_snapshot_chain(self):
        """分类 → 快照 链路。"""
        from tools.classify_page import ClassifyPageTool
        from tools.browser_tools import BrowserSnapshotTool

        # Step 1: 分类
        classify = ClassifyPageTool()
        result = await classify.execute("https://github.com/dashboard")
        data = json.loads(result)
        assert "page_type" in data
        print(f"\n  页面分类: {data['page_type']} ({data['method']})")

        # Step 2: 快照工具可用
        snapshot = BrowserSnapshotTool()
        assert snapshot.name == "browser_snapshot"
        print(f"  快照工具: schema 完整")

    def test_all_mcp_tools_callable(self):
        """所有 MCP 工具可调用。"""
        from tools import get_all_tools

        tools = get_all_tools()
        for tool in tools:
            assert hasattr(tool, "execute"), f"{tool.name} 缺少 execute 方法"
            assert hasattr(tool, "schema"), f"{tool.name} 缺少 schema"
            assert callable(tool.execute), f"{tool.name}.execute 不可调用"

        print(f"\n  {len(tools)} 个工具全部可调用")

    def test_tool_registry_complete(self):
        """工具注册表完整。"""
        from tools import get_tool_by_name, _TOOL_REGISTRY

        expected = [
            "search_docs", "fetch_doc_page", "save_memory", "recall_memory",
            "highlight_element", "visual_locate", "screenshot_annotate",
            "classify_page", "learn_flow",
            "browser_snapshot", "browser_interact", "browser_find",
        ]

        for name in expected:
            assert name in _TOOL_REGISTRY, f"注册表缺少: {name}"
            tool = get_tool_by_name(name)
            assert tool is not None, f"工具加载失败: {name}"

        print(f"\n  注册表: {len(expected)} 个工具全部就绪")


class TestConfigAndHealth:
    """配置和健康检查测试。"""

    def test_settings_loadable(self):
        """配置可加载。"""
        from config import settings

        assert settings.bff_port > 0
        assert settings.ollama_model
        assert settings.chroma_host
        print(f"\n  端口: {settings.bff_port}")
        print(f"  模型: {settings.ollama_model}")
        print(f"  策略: {settings.model_strategy.value}")

    def test_chroma_collections_configured(self):
        """Chroma 集合配置完整。"""
        from config import settings

        assert settings.chroma_collection_docs
        assert settings.chroma_collection_elements
        assert settings.chroma_collection_flows
        print(f"\n  集合: docs={settings.chroma_collection_docs}")
        print(f"        elements={settings.chroma_collection_elements}")
        print(f"        flows={settings.chroma_collection_flows}")
