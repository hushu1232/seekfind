"""
求问 — 文档搜索工具
===================

职责：
  - 从本地文档索引中搜索与用户问题相关的信息
  - 采用混合检索策略：向量检索 + BM25 关键词检索 + RRF 融合排序

检索流程（优化后）：
  1. 向量检索：Chroma cosine 相似度，擅长语义匹配
  2. BM25 检索：jieba 分词 + rank-bm25，擅长关键词精确匹配
     - 优化：BM25 在全库语料上检索，而非仅在向量结果上
     - 优化：jieba 加载自定义词典（产品名、技术术语）
  3. RRF 融合：两路独立候选集合并，取 top_k

为什么用混合检索：
  - 纯向量检索：对中文同义词效果好，但对精确关键词可能漏检
  - 纯 BM25：关键词精确匹配好，但不理解语义
  - 混合 + RRF：兼顾两者优势

性能：
  - 向量检索：< 10ms
  - BM25 检索：< 50ms（千级文档，首次构建索引后缓存）
  - 总延迟：< 200ms
"""

import json
from dataclasses import dataclass, field

import jieba
import structlog
from rank_bm25 import BM25Okapi

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# jieba 自定义词典
# ---------------------------------------------------------------------------
_CUSTOM_WORDS = [
    # 产品名
    "GitHub", "GitLab", "Jira", "Confluence", "VS Code", "Chrome", "Firefox",
    "Docker", "Kubernetes", "K8s", "Slack", "Discord", "Teams", "Zoom",
    "飞书", "钉钉", "企业微信", "Notion", "Figma", "Canva", "Miro",
    "Trello", "Linear", "Postman", "Vercel", "AWS", "Azure", "GCP",
    "Obsidian", "Logseq", "Excel", "Word", "PowerPoint",
    "淘宝", "支付宝", "微信", "Gmail", "Outlook",
    # 技术术语
    "Pull Request", "Merge Request", "Issue", "Pipeline", "Deploy",
    "Container", "Pod", "Service", "Ingress", "ConfigMap",
    "Side Panel", "Content Script", "Service Worker", "Manifest",
    "WebSocket", "REST API", "GraphQL", "OAuth", "JWT",
    "向量检索", "语义搜索", "关键词匹配", "混合检索",
]

for word in _CUSTOM_WORDS:
    jieba.add_word(word)


# ---------------------------------------------------------------------------
# BM25 索引缓存
# ---------------------------------------------------------------------------
class BM25Index:
    """
    BM25 索引缓存。

    首次检索时从 Chroma 加载全库文档，构建 BM25 索引。
    后续检索直接使用缓存，直到文档数变化时重建。

    优化点：
      - 全库 BM25（而非仅在向量结果上检索）
      - jieba 自定义词典（产品名精确分词）
    """

    def __init__(self):
        self._corpus: list[dict] = []  # [{"text": ..., "metadata": ...}, ...]
        self._tokenized: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._corpus_size: int = 0

    async def ensure_ready(self, long_term_memory) -> None:
        """确保 BM25 索引就绪。如果文档数变化，重建索引。"""
        if not long_term_memory:
            return

        # 获取当前文档数
        try:
            coll = long_term_memory._collections.get("docs")
            if not coll:
                return
            current_size = coll.count()
        except Exception:
            return

        # 文档数变化或首次加载时重建
        if current_size != self._corpus_size or self._bm25 is None:
            await self._rebuild(long_term_memory, current_size)

    async def _rebuild(self, long_term_memory, size: int) -> None:
        """重建 BM25 索引。"""
        try:
            coll = long_term_memory._collections.get("docs")
            if not coll:
                return

            # 获取全库文档（限制 5000 条，防止内存爆炸）
            limit = min(size, 5000)
            results = coll.get(limit=limit)

            self._corpus = []
            self._tokenized = []
            for i, doc in enumerate(results.get("documents", [])):
                meta = results.get("metadatas", [{}])[i] if results.get("metadatas") else {}
                self._corpus.append({"text": doc, "metadata": meta})
                # jieba 分词（使用自定义词典）
                tokens = list(jieba.cut(doc))
                self._tokenized.append(tokens)

            self._bm25 = BM25Okapi(self._tokenized)
            self._corpus_size = size

            logger.info("BM25 索引重建完成", corpus_size=len(self._corpus))

        except Exception as e:
            logger.warning("BM25 索引重建失败", error=str(e))

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """在全库 BM25 索引上检索。"""
        if not self._bm25 or not self._corpus:
            return []

        tokenized_query = list(jieba.cut(query))
        scores = self._bm25.get_scores(tokenized_query)

        # 按分数排序，取 top_k
        scored = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for idx, score in scored:
            if score > 0:  # 过滤零分
                results.append({
                    **self._corpus[idx],
                    "bm25_score": float(score),
                })
        return results


# 全局 BM25 索引缓存
_bm25_index = BM25Index()


# ---------------------------------------------------------------------------
# 搜索工具
# ---------------------------------------------------------------------------
@dataclass
class SearchDocsTool:
    """混合文档检索工具。"""

    name: str = "search_docs"
    description: str = (
        "从本地文档索引中搜索相关信息。"
        "当用户问关于产品使用、操作步骤、功能说明等问题时调用。"
    )
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

        优化后的流程：
          1. 向量检索 Chroma（top_k）
          2. 全库 BM25 检索（top_k）— 独立候选集
          3. RRF 融合两路结果，取 top_k
        """
        if not long_term_memory:
            return json.dumps({"results": [], "message": "索引未初始化，请先导入文档"})

        # Step 1: 向量检索
        vector_results = await long_term_memory.search(
            query=query, collection="docs", top_k=top_k
        )

        # Step 2: 全库 BM25 检索（独立候选集）
        await _bm25_index.ensure_ready(long_term_memory)
        bm25_results = _bm25_index.search(query, top_k=top_k)

        # Step 3: RRF 融合
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

    def _rrf_merge(
        self, list_a: list[dict], list_b: list[dict], top_k: int, k: int = 60
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion (RRF) 融合排序。

        两路独立候选集合并：
          - list_a: 向量检索结果
          - list_b: 全库 BM25 检索结果
          - 两者可能有重叠，RRF 会给予重叠文档更高排名
        """
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
