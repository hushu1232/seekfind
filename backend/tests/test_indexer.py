"""
求问 — 索引引擎测试
===================

测试 IndexBuilder：
  - chunk_document 分块逻辑
  - build_from_docs 索引构建
  - build_from_builtin 常识库加载

测试 DocCrawler：
  - _extract_title
  - _extract_links
"""

import pytest
from indexer.build_index import IndexBuilder
from indexer.crawler import CrawledDoc, DocCrawler


class TestIndexBuilder:
    """IndexBuilder 测试。"""

    def test_chunk_document(self, sample_crawled_doc):
        """测试文档分块。"""
        builder = IndexBuilder(chunk_size=50, chunk_overlap=10)
        chunks = builder.chunk_document(sample_crawled_doc)

        assert len(chunks) > 1
        # 每个 chunk 有 id, text, metadata
        for chunk in chunks:
            assert "id" in chunk
            assert "text" in chunk
            assert "metadata" in chunk
            assert chunk["metadata"]["source_url"] == sample_crawled_doc.url
            assert chunk["metadata"]["title"] == sample_crawled_doc.title

    def test_chunk_document_small(self):
        """小文档只产生一个 chunk。"""
        builder = IndexBuilder(chunk_size=1000, chunk_overlap=50)
        doc = CrawledDoc(url="http://test.com", title="Test", text="短文档")
        chunks = builder.chunk_document(doc)
        assert len(chunks) == 1

    def test_chunk_overlap(self, sample_crawled_doc):
        """测试分块重叠。"""
        builder = IndexBuilder(chunk_size=50, chunk_overlap=10)
        chunks = builder.chunk_document(sample_crawled_doc)

        if len(chunks) > 1:
            # 第一个 chunk 的末尾应该和第二个 chunk 的开头有重叠
            first_end = chunks[0]["text"][-10:]
            second_start = chunks[1]["text"][:10]
            # 至少有部分重叠
            assert len(set(first_end) & set(second_start)) > 0

    @pytest.mark.asyncio
    async def test_build_from_docs(self, sample_crawled_doc, mock_long_term_memory):
        """测试从文档列表构建索引。"""
        builder = IndexBuilder(chunk_size=100, chunk_overlap=20)
        count = await builder.build_from_docs([sample_crawled_doc], mock_long_term_memory)

        assert count > 0
        mock_long_term_memory.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_from_builtin(self, tmp_knowledge_dir, mock_long_term_memory):
        """测试从内置常识库构建索引。"""
        builder = IndexBuilder()
        count = await builder.build_from_builtin(tmp_knowledge_dir, mock_long_term_memory)

        assert count == 2  # sample_builtin_json 有 2 个 entries
        mock_long_term_memory.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_from_builtin_empty_dir(self, tmp_path, mock_long_term_memory):
        """空目录返回 0。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        builder = IndexBuilder()
        count = await builder.build_from_builtin(str(empty_dir), mock_long_term_memory)
        assert count == 0


class TestDocCrawler:
    """DocCrawler 测试。"""

    def test_extract_title(self):
        """测试标题提取。"""
        html = "<html><head><title>测试标题</title></head><body></body></html>"
        title = DocCrawler._extract_title(html)
        assert title == "测试标题"

    def test_extract_title_empty(self):
        """无标题返回空字符串。"""
        html = "<html><body></body></html>"
        title = DocCrawler._extract_title(html)
        assert title == ""

    def test_extract_links(self):
        """测试链接提取。"""
        html = '''
        <html><body>
            <a href="/page1">Page 1</a>
            <a href="https://example.com/page2">Page 2</a>
            <a href="#anchor">Anchor</a>
            <a href="javascript:void(0)">JS</a>
            <a href="mailto:test@test.com">Email</a>
        </body></html>
        '''
        links = DocCrawler._extract_links(html, "example.com")
        # 只保留同域 http/https 链接
        assert len(links) >= 1
        assert not any("javascript:" in link for link in links)
        assert not any("mailto:" in link for link in links)

    def test_extract_links_limit(self):
        """每页最多 50 个链接。"""
        links_html = "".join([f'<a href="https://example.com/p{i}">P{i}</a>' for i in range(100)])
        html = f"<html><body>{links_html}</body></html>"
        links = DocCrawler._extract_links(html, "example.com")
        assert len(links) <= 50


class TestCrawledDoc:
    """CrawledDoc 数据结构测试。"""

    def test_default_fields(self):
        """新增字段有默认值（向后兼容）。"""
        doc = CrawledDoc(url="http://test.com", title="Test", text="Hello")
        assert doc.depth == 0
        assert doc.html == ""
        assert doc.status == 200
        assert doc.content_type == ""
        assert doc.fetched_at == 0.0
        assert doc.fetcher_type == "http"

    def test_all_fields(self):
        """所有字段可赋值。"""
        doc = CrawledDoc(
            url="http://test.com",
            title="Test",
            text="Hello",
            depth=1,
            html="<html>Hello</html>",
            status=200,
            content_type="text/html",
            fetched_at=1234567890.0,
            fetcher_type="scrapling_http",
        )
        assert doc.html == "<html>Hello</html>"
        assert doc.status == 200
        assert doc.fetcher_type == "scrapling_http"
