"""
求问 — Vision Worker
====================

视觉定位 Worker。复用 visual_locate 工具。
需要 moondream2 视觉模型支持。
"""

import asyncio
import json

import structlog

logger = structlog.get_logger()

WORKER_TIMEOUT = 8  # 秒


class VisionWorker:
    """视觉定位 Worker。"""

    def __init__(self, vision_model=None):
        self._model = vision_model

    async def execute(self, target: str, image_base64: str = "") -> dict:
        """
        执行视觉定位。

        Args:
            target: 目标元素描述
            image_base64: 截图 base64（可选）

        Returns:
            {"success": True, "location": {...}} 或 {"success": False, "error": "..."}
        """
        if not self._model:
            return {"success": False, "error": "视觉模型未加载"}

        try:
            from tools.visual_locate import VisualLocateTool
            tool = VisualLocateTool()

            result = await asyncio.wait_for(
                tool.execute(
                    image_base64=image_base64,
                    description=target,
                    vision_model=self._model,
                ),
                timeout=WORKER_TIMEOUT,
            )

            data = json.loads(result)
            if data.get("error"):
                return {"success": False, "error": data["error"]}

            return {"success": True, "location": data}

        except TimeoutError:
            logger.warning("Vision Worker 超时", target=target)
            return {"success": False, "error": "视觉定位超时"}
        except Exception as e:
            logger.warning("Vision Worker 异常", error=str(e))
            return {"success": False, "error": str(e)}
