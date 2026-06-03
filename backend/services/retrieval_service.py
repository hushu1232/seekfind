"""
求问 — 检索服务
===============

职责：
  1. 管理向量库连接
  2. 执行混合检索（向量 + BM25）
  3. RRF 融合排序
  4. 缓存检索结果
"""

import asyncio

import structlog
from core.cache import get_cache_manager
from core.observability import get_metrics, get_tracer

from .base import BaseService

logger = structlog.get_logger()


class RetrievalService(BaseService):
    """
    检索服务

    封装混合检索逻辑，提供统一的服务接口。
    """

    def __init__(self):
        super().__init__("retrieval")
        self._long_term = None
        self._bm25_index = None
        self._cache = get_cache_manager()
        self._metrics = get_metrics()
        self._tracer = get_tracer()

    async def initialize(self) -> None:
        """初始化检索服务"""
        from memory.long_term import LongTermMemory
        from tools.search_docs import BM25Index

        # 初始化向量库
        self._long_term = LongTermMemory()
        await self._long_term.initialize()

        # 初始化 BM25 索引
        self._bm25_index = BM25Index()

        logger.info("检索服务初始化完成")

    async def shutdown(self) -> None:
        """关闭检索服务"""
        if self._long_term:
            await self._long_term.close()
            self._long_term = None

        logger.info("检索服务已关闭")

    async def health_check(self) -> bool:
        """健康检查"""
        return self._long_term is not None

    async def search(
        self,
        query: str,
        top_k: int = 5,
        collection: str = "docs",
        use_cache: bool = True,
    ) -> list[dict]:
        """
        执行混合检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            collection: 集合名称
            use_cache: 是否使用缓存

        Returns:
            list[dict]: 检索结果
        """
        metrics = self._metrics
        tracer = self._tracer

        # 检查缓存
        if use_cache:
            cache_key = self._cache._generate_key("search", {
                "query": query,
                "top_k": top_k,
                "collection": collection,
            })
            cached = await self._cache.get(cache_key)
            if cached:
                metrics.increment("retrieval.cache.hits")
                return cached
            metrics.increment("retrieval.cache.misses")

        with tracer.start_span("retrieval.search") as span:
            span.attributes["query"] = query[:100]
            span.attributes["top_k"] = top_k

            start_time = __import__('time').time()

            try:
                # 并行执行向量检索和 BM25 检索
                vector_task = self._vector_search(query, top_k, collection)
                bm25_task = self._bm25_search(query, top_k)

                vector_results, bm25_results = await asyncio.gather(
                    vector_task, bm25_task,
                    return_exceptions=True,
                )

                # 处理异常
                if isinstance(vector_results, Exception):
                    logger.warning("向量检索失败", error=str(vector_results))
                    vector_results = []

                if isinstance(bm25_results, Exception):
                    logger.warning("BM25 检索失败", error=str(bm25_results))
                    bm25_results = []

                # RRF 融合
                merged = self._rrf_merge(vector_results, bm25_results, top_k * 2)

                # Reranker 精排
                reranked = await self._rerank(query, merged, top_k)

                # 缓存结果
                if use_cache:
                    await self._cache.set(cache_key, reranked)

                # 记录指标
                duration = __import__('time').time() - start_time
                metrics.observe("retrieval.search.duration", duration)
                metrics.increment("retrieval.search.total")

                span.attributes["vector_count"] = len(vector_results)
                span.attributes["bm25_count"] = len(bm25_results)
                span.attributes["result_count"] = len(reranked)

                return reranked

            except Exception as e:
                duration = __import__('time').time() - start_time
                metrics.increment("retrieval.search.errors")
                metrics.observe("retrieval.search.duration", duration)

                logger.error("检索失败", error=str(e))
                return []

    async def _vector_search(
        self,
        query: str,
        top_k: int,
        collection: str,
    ) -> list[dict]:
        """向量检索"""
        if not self._long_term:
            return []

        return await self._long_term.search(
            query=query,
            collection=collection,
            top_k=top_k,
        )

    async def _bm25_search(
        self,
        query: str,
        top_k: int,
    ) -> list[dict]:
        """BM25 检索"""
        if not self._bm25_index or not self._long_term:
            return []

        # 确保 BM25 索引就绪
        await self._bm25_index.ensure_ready(self._long_term)

        return self._bm25_index.search(query, top_k=top_k)

    async def _rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int,
    ) -> list[dict]:
        """Reranker 精排"""
        try:
            from utils.reranker import get_reranker
            reranker = get_reranker()
            if reranker._model:
                return reranker.rerank(query, candidates, top_k=top_k)
        except Exception as e:
            logger.debug("Reranker 不可用", error=str(e))

        return candidates[:top_k]

    def _rrf_merge(
        self,
        list_a: list[dict],
        list_b: list[dict],
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion (RRF) 融合排序

        Args:
            list_a: 向量检索结果
            list_b: BM25 检索结果
            top_k: 返回结果数量
            k: RRF 参数

        Returns:
            list[dict]: 融合后的结果
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

    async def add_document(
        self,
        text: str,
        metadata: dict | None = None,
        collection: str = "docs",
    ) -> str:
        """
        添加文档到向量库

        Args:
            text: 文档文本
            metadata: 文档元数据
            collection: 集合名称

        Returns:
            str: 文档 ID
        """
        if not self._long_term:
            raise RuntimeError("检索服务未初始化")

        doc_id = await self._long_term.add(
            text=text,
            metadata=metadata or {},
            collection=collection,
        )

        # 清除相关缓存
        await self._cache.invalidate_pattern("search:")

        self._metrics.increment("retrieval.documents.added")

        return doc_id
