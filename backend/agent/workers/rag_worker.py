"""
求问 — RAG Worker
=================

文档检索问答 Worker。复用 search_docs + fetch_doc_page 工具。
"""

import asyncio
import json
from typing import Any

import structlog

logger = structlog.get_logger()

WORKER_TIMEOUT = 10  # 秒


class RAGWorker:
    """RAG 检索 Worker。"""

    def __init__(self, long_term_memory=None):
        self._memory = long_term_memory

    async def execute(self, query: str) -> dict:
        """
        执行文档检索。

        Args:
            query: 检索关键词

        Returns:
            {"success": True, "results": [...]} 或 {"success": False, "error": "..."}
        """
        try:
            from tools.search_docs import SearchDocsTool
            tool = SearchDocsTool()

            result = await asyncio.wait_for(
                tool.execute(query=query, top_k=5, long_term_memory=self._memory),
                timeout=WORKER_TIMEOUT,
            )

            data = json.loads(result)
            return {"success": True, "results": data.get("results", [])}

        except asyncio.TimeoutError:
            logger.warning("RAG Worker 超时", query=query[:50])
            return {"success": False, "error": "检索超时"}
        except Exception as e:
            logger.warning("RAG Worker 异常", error=str(e))
            return {"success": False, "error": str(e)}
