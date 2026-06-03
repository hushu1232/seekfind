"""
求问 — 检索模块测试
===================

测试 search_docs 工具：
  - RRF 融合逻辑
  - BM25 索引构建
  - 混合检索流程
"""

import json

import jieba
import pytest
from tools.search_docs import BM25Index, SearchDocsTool


class TestRRFMerge:
    """RRF 融合排序测试。"""

    def test_merge_disjoint_results(self):
        """两路无重叠结果，按各自排名融合。"""
        tool = SearchDocsTool()
        list_a = [
            {"text": "文档A", "metadata": {}},
            {"text": "文档B", "metadata": {}},
        ]
        list_b = [
            {"text": "文档C", "metadata": {}},
            {"text": "文档D", "metadata": {}},
        ]
        merged = tool._rrf_merge(list_a, list_b, top_k=4)
        assert len(merged) == 4
        # 第一个结果应该是 list_a 的第一名（RRF 分数最高）
        assert merged[0]["text"] == "文档A"

    def test_merge_overlapping_results(self):
        """两路有重叠时，重叠文档排名更高。"""
        tool = SearchDocsTool()
        list_a = [
            {"text": "共享文档", "metadata": {}},
            {"text": "文档A", "metadata": {}},
        ]
        list_b = [
            {"text": "共享文档", "metadata": {}},
            {"text": "文档B", "metadata": {}},
        ]
        merged = tool._rrf_merge(list_a, list_b, top_k=3)
        # 共享文档在两路都排第一，RRF 分数应该最高
        assert merged[0]["text"] == "共享文档"

    def test_merge_top_k_limit(self):
        """结果数量不超过 top_k。"""
        tool = SearchDocsTool()
        list_a = [{"text": f"A{i}", "metadata": {}} for i in range(10)]
        list_b = [{"text": f"B{i}", "metadata": {}} for i in range(10)]
        merged = tool._rrf_merge(list_a, list_b, top_k=5)
        assert len(merged) == 5

    def test_merge_empty_lists(self):
        """空列表处理。"""
        tool = SearchDocsTool()
        merged = tool._rrf_merge([], [], top_k=5)
        assert len(merged) == 0


class TestBM25Index:
    """BM25 索引测试。"""

    def test_search_empty_index(self):
        """空索引返回空结果。"""
        idx = BM25Index()
        results = idx.search("测试")
        assert results == []

    def test_search_after_manual_build(self):
        """手动构建索引后可检索。"""
        idx = BM25Index()
        idx._corpus = [
            {"text": "GitHub 创建仓库教程", "metadata": {}},
            {"text": "Docker 容器部署指南", "metadata": {}},
            {"text": "VS Code 扩展安装方法", "metadata": {}},
        ]
        idx._tokenized = [list(jieba.cut(doc["text"])) for doc in idx._corpus]
        from rank_bm25 import BM25Okapi
        idx._bm25 = BM25Okapi(idx._tokenized)

        results = idx.search("GitHub 仓库", top_k=2)
        assert len(results) > 0
        assert "GitHub" in results[0]["text"]

    def test_custom_words_segmentation(self):
        """自定义词典应正确切分产品名。"""
        import jieba
        tokens = list(jieba.cut("怎么在GitHub上创建Pull Request"))
        # 自定义词典应确保 "GitHub" 和 "Pull Request" 作为整体
        assert "GitHub" in tokens


class TestSearchDocsTool:
    """SearchDocsTool 完整流程测试。"""

    def test_schema_format(self):
        tool = SearchDocsTool()
        assert tool.name == "search_docs"
        assert "query" in tool.schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_no_memory(self):
        tool = SearchDocsTool()
        result = await tool.execute("测试查询")
        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_execute_with_mock_memory(self, mock_long_term_memory):
        tool = SearchDocsTool()
        result = await tool.execute("测试查询", long_term_memory=mock_long_term_memory)
        data = json.loads(result)
        # 即使 BM25 索引为空，向量检索也应该返回结果
        assert len(data["results"]) > 0
