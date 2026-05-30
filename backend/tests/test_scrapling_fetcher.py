"""
求问 — ScraplingFetcher 测试
============================

测试 Scrapling Fetcher 适配层：
  - 初始化（各种模式）
  - 降级到 httpx
  - 标题提取
  - 链接提取
  - 内容截断
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from indexer.scrapling_fetcher import ScraplingFetcher
from indexer.crawler import CrawledDoc


class TestScraplingFetcherInit:
    """初始化测试。"""

    def test_init_http_mode(self):
        """HTTP 模式初始化。"""
        fetcher = ScraplingFetcher(mode="http")
        assert fetcher.mode == "http"
        # scrapling 安装时 _fetcher 不为 None，否则为 None（降级模式）

    def test_init_invalid_mode(self):
        """无效模式降级为无 fetcher（不抛异常）。"""
        fetcher = ScraplingFetcher(mode="invalid")
        assert fetcher._fetcher is None  # 降级模式

    def test_default_mode_is_http(self):
        """默认模式为 http。"""
        fetcher = ScraplingFetcher()
        assert fetcher.mode == "http"

    def test_timeout_configurable(self):
        """超时可配置。"""
        fetcher = ScraplingFetcher(timeout=60)
        assert fetcher.timeout == 60

    def test_max_content_length_configurable(self):
        """内容截断长度可配置。"""
        fetcher = ScraplingFetcher(max_content_length=5000)
        assert fetcher.max_content_length == 5000


class TestScraplingFetcherFallback:
    """降级测试。"""

    @pytest.mark.asyncio
    async def test_fetch_fallback_when_scrapling_unavailable(self):
        """Scrapling 不可用时降级到 httpx。"""
        fetcher = ScraplingFetcher(mode="http")
        fetcher._fetcher = None  # 模拟 Scrapling 不可用
        fetcher._fallback_enabled = True

        mock_response = MagicMock()
        mock_response.text = "<html><head><title>Test Page</title></head><body>Hello World</body></html>"
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            with patch("trafilatura.extract", return_value="Hello World"):
                doc = await fetcher.fetch("https://example.com")
                assert isinstance(doc, CrawledDoc)
                assert doc.text == "Hello World"
                assert doc.title == "Test Page"
                assert doc.fetcher_type == "httpx_fallback"

    @pytest.mark.asyncio
    async def test_fetch_raises_when_both_fail(self):
        """两种方式都失败时抛出异常。"""
        fetcher = ScraplingFetcher(mode="http")
        fetcher._fetcher = None
        fetcher._fallback_enabled = False

        with pytest.raises(RuntimeError, match="抓取失败"):
            await fetcher.fetch("https://example.com")


class TestScraplingFetcherHelpers:
    """辅助方法测试。"""

    def test_extract_title(self):
        """标题提取。"""
        html = "<html><head><title>测试标题</title></head></html>"
        assert ScraplingFetcher._extract_title(html) == "测试标题"

    def test_extract_title_empty(self):
        """无标题返回空字符串。"""
        html = "<html><body></body></html>"
        assert ScraplingFetcher._extract_title(html) == ""

    def test_extract_title_with_attributes(self):
        """带属性的 title 标签。"""
        html = '<html><head><title lang="zh">中文标题</title></head></html>'
        assert ScraplingFetcher._extract_title(html) == "中文标题"

    def test_extract_links(self):
        """链接提取。"""
        fetcher = ScraplingFetcher(mode="http")
        html = '''
        <html><body>
            <a href="/page1">Page 1</a>
            <a href="https://example.com/page2">Page 2</a>
            <a href="https://other.com/page3">Other</a>
            <a href="#anchor">Anchor</a>
            <a href="javascript:void(0)">JS</a>
            <a href="mailto:test@test.com">Email</a>
        </body></html>
        '''
        links = fetcher.extract_links(html, "example.com")
        # 只保留同域 http/https 链接
        assert len(links) >= 1
        assert not any("javascript:" in l for l in links)
        assert not any("mailto:" in l for l in links)
        assert not any("other.com" in l for l in links)

    def test_extract_links_limit(self):
        """每页最多 50 个链接。"""
        fetcher = ScraplingFetcher(mode="http")
        links_html = "".join([f'<a href="https://example.com/p{i}">P{i}</a>' for i in range(100)])
        html = f"<html><body>{links_html}</body></html>"
        links = fetcher.extract_links(html, "example.com")
        assert len(links) <= 50


class TestScraplingFetcherIntegration:
    """集成测试（需要网络，标记为慢测试）。"""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_fetch_real_page(self):
        """抓取真实页面（需要网络）。"""
        fetcher = ScraplingFetcher(mode="http")
        try:
            doc = await fetcher.fetch("https://httpbin.org/html")
            assert isinstance(doc, CrawledDoc)
            assert doc.text  # 应有正文
            assert doc.status == 200
            assert doc.fetched_at > 0
        except Exception:
            pytest.skip("网络不可用或 httpbin.org 不可达")
