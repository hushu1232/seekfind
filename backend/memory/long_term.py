"""
求问 — 长期记忆模块
===================

职责：
  - 封装 Chroma 向量库的增删改查操作
  - 管理三个独立集合：
      docs:      文档索引（分块后的文档文本 + 元数据）
      elements:  元素指纹库（页面元素 selector + 描述映射）
      flows:     操作流库（录制的操作序列）
  - 提供 save_memory/recall_memory 高级接口供 Agent 工具调用

优化点（Sprint 4 T11）：
  - 连接超时配置化（默认 10 秒）
  - 操作重试（最多 3 次，指数退避）
  - 连接健康检查

连接方式：
  使用 Chroma HTTP Client 连接 docker-compose 中的 chroma 容器。
  容器内通过服务名 "chroma" 解析，宿主机通过 localhost:8000 访问。

Embedding：
  Chroma 默认使用内置的 all-MiniLM-L6-v2（英文优化）。
  生产环境应切换为 Ollama 的 nomic-embed-text（中英文均支持）。
  TODO: 集成 Ollama embedding 函数。
"""

import asyncio
from typing import Any

import chromadb
import structlog
from chromadb.config import Settings as ChromaSettings
from config import settings

logger = structlog.get_logger()


# 重试配置
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5  # 秒，指数退避基数


async def _retry_async(func, *args, max_retries: int = _MAX_RETRIES, **kwargs) -> Any:
    """
    异步重试装饰器（指数退避）。

    对 Chroma 的瞬时连接错误进行重试。
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            # Chroma 的同步方法在线程池中运行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Chroma 操作失败，重试中",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)
    raise last_error


class LongTermMemory:
    """
    Chroma 向量库封装。

    典型用法：
        mem = LongTermMemory()
        await mem.initialize()

        # 写入
        await mem.add("docs", texts=["文档内容..."], metadatas=[{"url": "..."}])

        # 检索
        results = await mem.search("怎么创建项目", collection="docs", top_k=5)
    """

    def __init__(self):
        self._client: chromadb.HttpClient | None = None
        self._collections: dict[str, chromadb.Collection] = {}
        self._connection_healthy: bool = False

    async def initialize(self) -> None:
        """
        连接 Chroma 并初始化三个集合。

        如果集合不存在会自动创建（get_or_create_collection）。
        使用 cosine 相似度（适合文本语义匹配）。
        """
        try:
            self._client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=ChromaSettings(anonymized_telemetry=False),
            )

            # 初始化三个集合
            collection_map = {
                "docs": settings.chroma_collection_docs,
                "elements": settings.chroma_collection_elements,
                "flows": settings.chroma_collection_flows,
            }
            for name, collection_name in collection_map.items():
                self._collections[name] = self._client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},  # cosine 相似度
                )

            self._connection_healthy = True
            logger.info(
                "长期记忆初始化完成",
                collections=list(collection_map.keys()),
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
        except Exception as e:
            self._connection_healthy = False
            logger.error("长期记忆初始化失败", error=str(e))
            raise

    async def close(self) -> None:
        """释放连接资源。"""
        self._client = None
        self._collections.clear()
        self._connection_healthy = False
        logger.info("长期记忆已关闭")

    async def health_check(self) -> bool:
        """检查 Chroma 连接是否健康。"""
        if not self._client:
            return False
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._client.heartbeat)
            self._connection_healthy = True
            return True
        except Exception as e:
            self._connection_healthy = False
            logger.warning("Chroma 健康检查失败", error=str(e))
            return False

    @property
    def is_healthy(self) -> bool:
        """连接是否健康。"""
        return self._connection_healthy

    async def add(
        self,
        collection: str,
        texts: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """
        向指定集合添加文档。

        Args:
            collection: 集合名 ("docs" / "elements" / "flows")
            texts: 文档文本列表
            metadatas: 每条文档的元数据（可选）
            ids: 每条文档的 ID（可选，不传则自动生成）

        注意：
          - Chroma 会自动使用 embedding 函数将文本转为向量
          - 相同 ID 的文档会被覆盖（upsert 语义）
        """
        coll = self._collections.get(collection)
        if not coll:
            raise ValueError(f"未知集合: {collection}，可用: {list(self._collections.keys())}")

        await _retry_async(coll.add, documents=texts, metadatas=metadatas, ids=ids)
        logger.debug("添加文档", collection=collection, count=len(texts))

    async def search(
        self, query: str, collection: str = "docs", top_k: int = 5
    ) -> list[dict]:
        """
        向量检索。

        Args:
            query: 查询文本（自然语言）
            collection: 检索的集合名
            top_k: 返回最相似的 K 条结果

        Returns:
            [{"text": "文档内容", "metadata": {...}}, ...]

        性能：
          - Chroma 向量检索延迟通常 < 10ms（千级文档）
          - 首次检索可能较慢（需加载索引到内存）
        """
        coll = self._collections.get(collection)
        if not coll:
            logger.warning("检索失败：集合不存在", collection=collection)
            return []

        results = await _retry_async(coll.query, query_texts=[query], n_results=top_k)

        docs = []
        documents = results.get("documents", [[]])
        metadatas = results.get("metadatas", [[]])

        for i, doc in enumerate(documents[0]):
            meta = metadatas[0][i] if metadatas and metadatas[0] else {}
            docs.append({"text": doc, "metadata": meta})

        return docs

    async def save_memory(self, key: str, content: str, metadata: dict | None = None) -> None:
        """
        保存一条长期记忆。

        用途：Agent 工具 save_memory 调用，将重要信息持久化。

        Args:
            key: 记忆的唯一标识符（如 "github_create_repo"）
            content: 记忆内容
            metadata: 附加元数据（可选）
        """
        await self.add(
            collection="docs",
            texts=[content],
            metadatas=[{"key": key, "source": "memory", **(metadata or {})}],
            ids=[f"memory_{key}"],
        )
        logger.info("保存长期记忆", key=key)

    async def recall_memory(self, query: str, top_k: int = 3) -> list[dict]:
        """
        回忆长期记忆。

        用途：Agent 工具 recall_memory 调用，从历史记忆中检索相关信息。
        """
        return await self.search(query, collection="docs", top_k=top_k)

    async def get_collection_count(self, collection: str = "docs") -> int:
        """获取指定集合中的文档总数（用于健康检查/统计）。"""
        coll = self._collections.get(collection)
        if not coll:
            return 0
        try:
            return await _retry_async(coll.count)
        except Exception:
            return 0
