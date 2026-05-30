"""
求问 — 文档搜索工具
===================

职责：
  - 从本地文档索引中搜索与用户问题相关的信息
  - 采用混合检索策略：向量检索 + BM25 关键词检索 + RRF 融合排序

检索流程：
  1. 向量检索：Chroma cosine 相似度，擅长语义匹配
  2. BM25 检索：jieba 分词 + rank-bm25，擅长关键词精确匹配
  3. RRF 融合：Reciprocal Rank Fusion，综合两种排序结果

为什么用混合检索：
  - 纯向量检索：对中文同义词/近义词效果好，但对精确关键词（如产品名、命令）可能漏检
  - 纯 BM25：关键词精确匹配好，但不理解语义
  - 混合 + RRF：兼顾两者优势，是 RAG 系统的最佳实践

性能：
  - 向量检索：< 10ms（Chroma 内存索引）
  - BM25 检索：< 5ms（纯 Python 计算）
  - 总延迟：< 50ms（千级文档）
"""

import json
from dataclasses import dataclass

import jieba
import structlog
from rank_bm25 import BM25Okapi

logger = structlog.get_logger()


@dataclass
class SearchDocsTool:
    """
    混合文档检索工具。

    Attributes:
        name: 工具名（Function Calling 时的 function name）
        description: 工具描述（LLM 用于判断何时调用）
        schema: Function Calling schema（OpenAI 格式）
    """

    name: str = "search_docs"
    description: str = (
        "从本地文档索引中搜索相关信息。"
        "当用户问关于产品使用、操作步骤、功能说明等问题时调用。"
    )
    schema: dict = None

    def __post_init__(self):
        """初始化 Function Calling schema。"""
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询文本，应包含用户问题的核心关键词",
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
        """
        执行混合检索。

        Args:
            query: 用户查询文本
            top_k: 返回结果数量
            long_term_memory: LongTermMemory 实例（由 Agent 注入）

        Returns:
            JSON 字符串：{"results": [{"text": "...", "score": 0.85}, ...]}

        流程：
          1. 向量检索 Chroma（top_k * 2，多取一些给 BM25 用作语料）
          2. BM25 在向量结果上做二次检索（避免全库扫描）
          3. RRF 融合两种排序，取 top_k
        """
        if not long_term_memory:
            return json.dumps({"results": [], "message": "索引未初始化，请先导入文档"})

        # Step 1: 向量检索（多取一些，作为 BM25 的候选集）
        vector_results = await long_term_memory.search(
            query=query, collection="docs", top_k=top_k * 2
        )

        # Step 2: BM25 检索（在向量结果的文本上做关键词匹配）
        bm25_results = self._bm25_search(query, vector_results, top_k)

        # Step 3: RRF 融合排序
        merged = self._rrf_merge(vector_results, bm25_results, top_k)

        logger.info(
            "文档检索完成",
            query=query[:50],
            vector_count=len(vector_results),
            bm25_count=len(bm25_results),
            merged_count=len(merged),
        )

        return json.dumps(
            {"results": [{"text": r["text"], "score": round(r.get("score", 0), 4)} for r in merged]},
            ensure_ascii=False,
        )

    def _bm25_search(self, query: str, corpus: list[dict], top_k: int) -> list[dict]:
        """
        BM25 关键词检索。

        在给定的语料集上使用 jieba 分词 + BM25 算法排序。

        Args:
            query: 查询文本
            corpus: 候选文档列表（来自向量检索结果）
            top_k: 返回数量

        Returns:
            按 BM25 分数排序的文档列表
        """
        if not corpus:
            return []

        # jieba 中文分词
        tokenized_corpus = [list(jieba.cut(doc.get("text", ""))) for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = list(jieba.cut(query))
        scores = bm25.get_scores(tokenized_query)

        # 按分数降序排列
        scored = sorted(zip(scores, corpus), key=lambda x: x[0], reverse=True)
        return [{**doc, "score": float(score)} for score, doc in scored[:top_k]]

    def _rrf_merge(
        self, list_a: list[dict], list_b: list[dict], top_k: int, k: int = 60
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion (RRF) 融合排序。

        RRF 公式：score(d) = Σ 1 / (k + rank_i(d))
        其中 k=60 是经验常数（论文推荐值）。

        优点：
          - 不需要归一化不同检索器的分数
          - 对排名靠前的文档给予更高权重
          - 简单有效，是混合检索的标准做法

        Args:
            list_a: 向量检索结果
            list_b: BM25 检索结果
            top_k: 最终返回数量
            k: RRF 常数（默认 60）

        Returns:
            融合排序后的文档列表
        """
        scores: dict[str, float] = {}
        doc_map: dict[str, dict] = {}

        # 用文本前 100 字符作为去重 key（避免重复计算）
        for rank, doc in enumerate(list_a):
            key = doc.get("text", "")[:100]
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            doc_map[key] = doc

        for rank, doc in enumerate(list_b):
            key = doc.get("text", "")[:100]
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            doc_map[key] = doc

        # 按 RRF 分数降序排列
        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        return [{**doc_map[key], "score": scores[key]} for key in sorted_keys[:top_k]]


# ---------------------------------------------------------------------------
# 工具实例（单例）
# ---------------------------------------------------------------------------
search_docs_tool = SearchDocsTool()
