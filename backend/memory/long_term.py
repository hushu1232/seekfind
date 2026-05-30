"""
求问 — 长期记忆（Chroma 向量库封装）
管理三个集合：docs（文档）、elements（元素指纹）、flows（操作流）。
"""

import structlog
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings

logger = structlog.get_logger()


class LongTermMemory:
    """Chroma 向量库封装。"""

    def __init__(self):
        self._client: chromadb.HttpClient | None = None
        self._collections: dict[str, chromadb.Collection] = {}

    async def initialize(self):
        """连接 Chroma 并初始化集合。"""
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # 创建/获取三个集合
        for name, collection_name in [
            ("docs", settings.chroma_collection_docs),
            ("elements", settings.chroma_collection_elements),
            ("flows", settings.chroma_collection_flows),
        ]:
            self._collections[name] = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        logger.info("长期记忆初始化完成")

    async def close(self):
        """释放资源。"""
        self._client = None
        self._collections.clear()

    async def add(
        self,
        collection: str,
        texts: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ):
        """向指定集合添加文档。"""
        coll = self._collections.get(collection)
        if not coll:
            raise ValueError(f"未知集合: {collection}")
        coll.add(documents=texts, metadatas=metadatas, ids=ids)
        logger.debug("添加文档", collection=collection, count=len(texts))

    async def search(
        self, query: str, collection: str = "docs", top_k: int = 5
    ) -> list[dict]:
        """向量检索。"""
        coll = self._collections.get(collection)
        if not coll:
            return []
        results = coll.query(query_texts=[query], n_results=top_k)
        docs = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
            docs.append({"text": doc, "metadata": meta})
        return docs

    async def save_memory(self, key: str, content: str, metadata: dict | None = None):
        """保存一条长期记忆。"""
        await self.add(
            collection="docs",
            texts=[content],
            metadatas=[{"key": key, **(metadata or {})}],
            ids=[f"memory_{key}"],
        )

    async def recall_memory(self, query: str, top_k: int = 3) -> list[dict]:
        """回忆长期记忆。"""
        return await self.search(query, collection="docs", top_k=top_k)
