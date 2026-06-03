"""
求问 — Highlight Worker
=======================

高亮元素 Worker。复用 highlight_element 工具。
"""

import asyncio
import json

import structlog

logger = structlog.get_logger()

WORKER_TIMEOUT = 5  # 秒


class HighlightWorker:
    """高亮元素 Worker。"""

    def __init__(self, fingerprint_storage=None):
        self._storage = fingerprint_storage

    async def execute(self, selector: str, description: str, page_url: str = "") -> dict:
        """
        执行元素高亮。

        Args:
            selector: CSS 选择器
            description: 元素描述
            page_url: 当前页面 URL

        Returns:
            {"success": True, "highlight": {...}} 或 {"success": False, "error": "..."}
        """
        try:
            from tools.highlight_element import HighlightElementTool
            tool = HighlightElementTool()

            result = await asyncio.wait_for(
                tool.execute(
                    selector=selector,
                    description=description,
                    page_url=page_url,
                    fingerprint_storage=self._storage,
                ),
                timeout=WORKER_TIMEOUT,
            )

            data = json.loads(result)
            if data.get("error"):
                return {"success": False, "error": data["error"]}

            return {"success": True, "highlight": data}

        except TimeoutError:
            logger.warning("Highlight Worker 超时", selector=selector)
            return {"success": False, "error": "高亮超时"}
        except Exception as e:
            logger.warning("Highlight Worker 异常", error=str(e))
            return {"success": False, "error": str(e)}
