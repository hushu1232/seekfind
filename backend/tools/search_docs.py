"""
求问 — 文档搜索工具
Chroma 向量检索 + BM25 关键词检索 + RRF 融合排序。
"""

import json
from dataclasses import dataclass

import jieba
import structlog
from rank_bm25 import BM25Okapi

logger = structlog.get_logger()


@dataclass
class SearchDocsTool:
    """混合检索工具。"""

    name: str = "search_docs"
    description: str = "从本地文档索引中搜索相关信息。当用户问关于产品使用、操作步骤等问题时调用。"
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询文本",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        }

    async def execute(self, query: str, top_k: int = 5, long_term_memory=None) -> str:
        """执行混合检索。"""
        if not long_term_memory:
            return json.dumps({"results": [], "message": "索引未初始化"})

        # 向量检索
        vector_results = await long_term_memory.search(
            query=query, collection="docs", top_k=top_k * 2
        )

        # BM25 检索（如果有语料）
        bm25_results = self._bm25_search(query, vector_results, top_k)

        # RRF 融合
        merged = self._rrf_merge(vector_results, bm25_results, top_k)

        return json.dumps(
            {"results": [{"text": r["text"], "score": r.get("score", 0)} for r in merged]},
            ensure_ascii=False,
        )

    def _bm25_search(self, query: str, corpus: list[dict], top_k: int) -> list[dict]:
        """BM25 关键词检索。"""
        if not corpus:
            return []
        tokenized_corpus = [list(jieba.cut(doc.get("text", ""))) for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = list(jieba.cut(query))
        scores = bm25.get_scores(tokenized_query)
        # 按分数排序
        scored = sorted(zip(scores, corpus), key=lambda x: x[0], reverse=True)
        return [{**doc, "score": float(score)} for score, doc in scored[:top_k]]

    def _rrf_merge(
        self, list_a: list[dict], list_b: list[dict], top_k: int, k: int = 60
    ) -> list[dict]:
        """Reciprocal Rank Fusion 融合排序。"""
        scores: dict[str, float] = {}
        doc_map: dict[str, dict] = {}

        for rank, doc in enumerate(list_a):
            key = doc.get("text", "")[:100]
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            doc_map[key] = doc

        for rank, doc in enumerate(list_b):
            key = doc.get("text", "")[:100]
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            doc_map[key] = doc

        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        return [{**doc_map[key], "score": scores[key]} for key in sorted_keys[:top_k]]


search_docs_tool = SearchDocsTool()
