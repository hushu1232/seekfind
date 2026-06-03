"""
求问 — 向量库适配器
==================

职责：
  1. 定义统一的向量库接口
  2. 支持多种向量库后端
  3. 平滑迁移

支持的向量库：
  - Chroma: 默认，适合小规模
  - Milvus: 适合大规模
  - Qdrant: 适合生产环境

使用方法：
  store = create_vector_store("chroma", config)
  await store.search(query_vector, top_k=5)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    text: str
    metadata: dict[str, Any]
    score: float


@dataclass
class VectorStoreConfig:
    """向量库配置"""
    store_type: str = "chroma"
    host: str = "localhost"
    port: int = 8000
    collection_name: str = "qiuwen_docs"
    dimension: int = 768


class VectorStore(ABC):
    """向量库基类"""

    @abstractmethod
    async def initialize(self) -> None:
        """初始化向量库"""
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict | None = None,
    ) -> list[SearchResult]:
        """
        向量搜索

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            filter_expr: 过滤表达式

        Returns:
            list[SearchResult]: 搜索结果
        """
        pass

    @abstractmethod
    async def insert(
        self,
        texts: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> list[str]:
        """
        插入向量

        Args:
            texts: 文本列表
            vectors: 向量列表
            metadata: 元数据列表

        Returns:
            list[str]: 插入的 ID 列表
        """
        pass

    @abstractmethod
    async def delete(self, ids: list[str]) -> None:
        """
        删除向量

        Args:
            ids: ID 列表
        """
        pass

    @abstractmethod
    async def get_collection_stats(self) -> dict[str, Any]:
        """获取集合统计信息"""
        pass

    async def close(self) -> None:
        """关闭连接"""
        pass


class ChromaVectorStore(VectorStore):
    """Chroma 向量库适配器"""

    def __init__(self, config: VectorStoreConfig):
        self._config = config
        self._client = None
        self._collection = None

    async def initialize(self) -> None:
        """初始化 Chroma"""
        try:
            import chromadb

            if self._config.host == "localhost":
                self._client = chromadb.PersistentClient(path="./data/chroma")
            else:
                self._client = chromadb.HttpClient(
                    host=self._config.host,
                    port=self._config.port,
                )

            self._collection = self._client.get_or_create_collection(
                name=self._config.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            logger.info("Chroma 初始化成功", collection=self._config.collection_name)

        except Exception as e:
            logger.error("Chroma 初始化失败", error=str(e))
            raise

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict | None = None,
    ) -> list[SearchResult]:
        """搜索"""
        if not self._collection:
            raise RuntimeError("Chroma 未初始化")

        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filter_expr,
        )

        search_results = []
        for i in range(len(results["ids"][0])):
            search_results.append(SearchResult(
                id=results["ids"][0][i],
                text=results["documents"][0][i],
                metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                score=1 - results["distances"][0][i] if results["distances"] else 0,
            ))

        return search_results

    async def insert(
        self,
        texts: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> list[str]:
        """插入"""
        if not self._collection:
            raise RuntimeError("Chroma 未初始化")

        ids = [f"doc_{i}" for i in range(len(texts))]

        self._collection.add(
            ids=ids,
            documents=texts,
            embeddings=vectors,
            metadatas=metadata,
        )

        return ids

    async def delete(self, ids: list[str]) -> None:
        """删除"""
        if not self._collection:
            raise RuntimeError("Chroma 未初始化")

        self._collection.delete(ids=ids)

    async def get_collection_stats(self) -> dict[str, Any]:
        """获取统计"""
        if not self._collection:
            raise RuntimeError("Chroma 未初始化")

        count = self._collection.count()
        return {
            "name": self._config.collection_name,
            "count": count,
            "type": "chroma",
        }


class MilvusVectorStore(VectorStore):
    """Milvus 向量库适配器"""

    def __init__(self, config: VectorStoreConfig):
        self._config = config
        self._client = None

    async def initialize(self) -> None:
        """初始化 Milvus"""
        try:
            from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType

            connections.connect(
                alias="default",
                host=self._config.host,
                port=self._config.port,
            )

            # 定义 schema
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self._config.dimension),
            ]
            schema = CollectionSchema(fields=fields)

            self._client = Collection(
                name=self._config.collection_name,
                schema=schema,
            )

            logger.info("Milvus 初始化成功", collection=self._config.collection_name)

        except ImportError:
            logger.error("pymilvus 未安装，请运行: pip install pymilvus")
            raise
        except Exception as e:
            logger.error("Milvus 初始化失败", error=str(e))
            raise

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict | None = None,
    ) -> list[SearchResult]:
        """搜索"""
        if not self._client:
            raise RuntimeError("Milvus 未初始化")

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        results = self._client.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=["text"],
        )

        search_results = []
        for hits in results:
            for hit in hits:
                search_results.append(SearchResult(
                    id=hit.id,
                    text=hit.entity.get("text", ""),
                    metadata={},
                    score=hit.score,
                ))

        return search_results

    async def insert(
        self,
        texts: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> list[str]:
        """插入"""
        if not self._client:
            raise RuntimeError("Milvus 未初始化")

        ids = [f"doc_{i}" for i in range(len(texts))]

        self._client.insert([
            ids,
            texts,
            vectors,
        ])

        return ids

    async def delete(self, ids: list[str]) -> None:
        """删除"""
        if not self._client:
            raise RuntimeError("Milvus 未初始化")

        self._client.delete(ids=ids)

    async def get_collection_stats(self) -> dict[str, Any]:
        """获取统计"""
        if not self._client:
            raise RuntimeError("Milvus 未初始化")

        self._client.load()
        count = self._client.num_entities
        return {
            "name": self._config.collection_name,
            "count": count,
            "type": "milvus",
        }


class QdrantVectorStore(VectorStore):
    """Qdrant 向量库适配器"""

    def __init__(self, config: VectorStoreConfig):
        self._config = config
        self._client = None

    async def initialize(self) -> None:
        """初始化 Qdrant"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(
                host=self._config.host,
                port=self._config.port,
            )

            # 检查集合是否存在
            collections = self._client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self._config.collection_name not in collection_names:
                self._client.create_collection(
                    collection_name=self._config.collection_name,
                    vectors_config=VectorParams(
                        size=self._config.dimension,
                        distance=Distance.COSINE,
                    ),
                )

            logger.info("Qdrant 初始化成功", collection=self._config.collection_name)

        except ImportError:
            logger.error("qdrant_client 未安装，请运行: pip install qdrant_client")
            raise
        except Exception as e:
            logger.error("Qdrant 初始化失败", error=str(e))
            raise

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict | None = None,
    ) -> list[SearchResult]:
        """搜索"""
        if not self._client:
            raise RuntimeError("Qdrant 未初始化")

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # 构建过滤条件
        query_filter = None
        if filter_expr:
            conditions = []
            for key, value in filter_expr.items():
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
            query_filter = Filter(must=conditions)

        results = self._client.search(
            collection_name=self._config.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )

        search_results = []
        for hit in results:
            search_results.append(SearchResult(
                id=str(hit.id),
                text=hit.payload.get("text", ""),
                metadata=hit.payload,
                score=hit.score,
            ))

        return search_results

    async def insert(
        self,
        texts: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> list[str]:
        """插入"""
        if not self._client:
            raise RuntimeError("Qdrant 未初始化")

        from qdrant_client.models import PointStruct

        ids = [f"doc_{i}" for i in range(len(texts))]

        points = []
        for i in range(len(texts)):
            payload = {"text": texts[i], **metadata[i]}
            points.append(PointStruct(
                id=i,
                vector=vectors[i],
                payload=payload,
            ))

        self._client.upsert(
            collection_name=self._config.collection_name,
            points=points,
        )

        return ids

    async def delete(self, ids: list[str]) -> None:
        """删除"""
        if not self._client:
            raise RuntimeError("Qdrant 未初始化")

        from qdrant_client.models import PointIdsList

        self._client.delete(
            collection_name=self._config.collection_name,
            points_selector=PointIdsList(points=ids),
        )

    async def get_collection_stats(self) -> dict[str, Any]:
        """获取统计"""
        if not self._client:
            raise RuntimeError("Qdrant 未初始化")

        info = self._client.get_collection(self._config.collection_name)
        return {
            "name": self._config.collection_name,
            "count": info.points_count,
            "type": "qdrant",
        }


def create_vector_store(
    store_type: str,
    config: dict[str, Any] | None = None,
) -> VectorStore:
    """
    创建向量库实例

    Args:
        store_type: 向量库类型 (chroma, milvus, qdrant)
        config: 配置参数

    Returns:
        VectorStore: 向量库实例
    """
    store_config = VectorStoreConfig(**(config or {}))
    store_config.store_type = store_type

    if store_type == "chroma":
        return ChromaVectorStore(store_config)
    elif store_type == "milvus":
        return MilvusVectorStore(store_config)
    elif store_type == "qdrant":
        return QdrantVectorStore(store_config)
    else:
        raise ValueError(f"不支持的向量库类型: {store_type}")
