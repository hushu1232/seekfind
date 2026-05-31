"""
求问 — Reranker 检索质量提升
===========================

在 RRF 融合排序之后，使用交叉编码器对候选结果进行精细排序。

方案：
  - 优先使用 sentence-transformers CrossEncoder（本地，准确）
  - 降级使用 LLM 重排序（通过 Ollama）
  - 最终降级使用关键词匹配分数

模型：
  - BAAI/bge-reranker-base（~1.1GB，准确率高）
  - BAAI/bge-reranker-v2-m3（多语言，~1.5GB）
"""

import structlog

logger = structlog.get_logger()


class Reranker:
    """
    检索结果重排序器。

    使用交叉编码器对 query-doc 对进行相关性打分。
    """

    def __init__(self):
        self._model = None
        self._model_name = "BAAI/bge-reranker-base"

    def initialize(self) -> bool:
        """初始化 reranker 模型。"""
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            logger.info("Reranker 初始化成功", model=self._model_name)
            return True
        except ImportError:
            logger.warning("sentence-transformers 未安装，Reranker 不可用")
            return False
        except Exception as e:
            logger.warning("Reranker 初始化失败", error=str(e))
            return False

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 5,
        text_key: str = "text",
    ) -> list[dict]:
        """
        对文档列表重排序。

        Args:
            query: 查询文本
            documents: 文档列表（每个 dict 包含 text_key 字段）
            top_k: 返回前 k 个结果
            text_key: 文本字段名

        Returns:
            重排序后的文档列表
        """
        if not documents:
            return []

        if not self._model:
            # 降级：返回原始顺序
            return documents[:top_k]

        # 构造 query-doc 对
        pairs = [(query, doc.get(text_key, "")) for doc in documents]

        # 预测相关性分数
        try:
            scores = self._model.predict(pairs)
        except Exception as e:
            logger.warning("Reranker 预测失败", error=str(e))
            return documents[:top_k]

        # 按分数排序
        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        return [doc for doc, _ in scored_docs[:top_k]]


# 全局单例
_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    """获取 Reranker 单例。"""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
