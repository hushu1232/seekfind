"""
求问 — Flow Worker
==================

操作流匹配 Worker。复用 learn_flow 工具。
"""

import asyncio
import json
from typing import Any

import structlog

logger = structlog.get_logger()

WORKER_TIMEOUT = 5  # 秒


class FlowWorker:
    """操作流匹配 Worker。"""

    def __init__(self, long_term_memory=None):
        self._memory = long_term_memory

    async def execute(self, intent: str) -> dict:
        """
        执行操作流匹配。

        Args:
            intent: 用户意图描述

        Returns:
            {"success": True, "flow": {...}} 或 {"success": False, "error": "..."}
        """
        try:
            from tools.learn_flow import LearnFlowTool
            tool = LearnFlowTool()

            result = await asyncio.wait_for(
                tool.execute(action="replay", flow_name=intent, long_term_memory=self._memory),
                timeout=WORKER_TIMEOUT,
            )

            data = json.loads(result)
            if data.get("error"):
                return {"success": False, "error": data["error"]}

            return {"success": True, "flow": data.get("flow")}

        except asyncio.TimeoutError:
            logger.warning("Flow Worker 超时", intent=intent)
            return {"success": False, "error": "操作流匹配超时"}
        except Exception as e:
            logger.warning("Flow Worker 异常", error=str(e))
            return {"success": False, "error": str(e)}
