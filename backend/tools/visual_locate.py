"""
求问 — 视觉定位工具
===================

职责：
  - 接收截图 (base64) + 元素描述
  - 调用 moondream2 视觉模型定位元素坐标
  - 返回 {x, y, w, h, confidence}

视觉定位流程：
  1. 前端截图 (chrome.tabs.captureVisibleTab)
  2. 截图发送到后端
  3. moondream2 分析截图，定位目标元素
  4. 返回坐标，前端计算对应 DOM 元素

置信度阈值：
  - confidence >= 0.7 → 直接高亮
  - 0.4 <= confidence < 0.7 → 降级到截图标注
  - confidence < 0.4 → 全部降级到截图标注

用法（Agent 工具调用）：
  result = await visual_locate_tool.execute(image_base64, "创建项目按钮")
"""

import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class VisualLocateTool:
    """
    视觉定位工具。

    依赖 MoondreamVision 实例（由 Agent 注入）。
    """

    name: str = "visual_locate"
    description: str = (
        "通过截图视觉分析定位页面元素的位置。"
        "当选择器定位失败时使用，作为降级方案。"
    )
    schema: dict = None

    # 置信度阈值
    CONFIDENCE_HIGH = 0.7    # 直接高亮
    CONFIDENCE_MEDIUM = 0.4  # 降级到截图标注

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "image_base64": {
                        "type": "string",
                        "description": "页面截图的 base64 编码",
                    },
                    "description": {
                        "type": "string",
                        "description": "要定位的元素描述（如 '创建项目按钮'）",
                    },
                },
                "required": ["image_base64", "description"],
            },
        }

    async def execute(
        self,
        image_base64: str,
        description: str,
        vision_model=None,
    ) -> str:
        """
        执行视觉定位。

        Args:
            image_base64: 页面截图 base64
            description: 元素描述
            vision_model: MoondreamVision 实例（由 Agent 注入）

        Returns:
            JSON 字符串：
              {"x": 100, "y": 200, "w": 80, "h": 30, "confidence": 0.85}
              或 {"error": "定位失败", "confidence": 0}
        """
        if not vision_model:
            return json.dumps({
                "error": "视觉模型未加载",
                "confidence": 0,
            })

        try:
            result = await vision_model.locate_element(image_base64, description)
            confidence = result.get("confidence", 0)

            logger.info(
                "视觉定位完成",
                description=description,
                confidence=confidence,
                x=result.get("x"),
                y=result.get("y"),
            )

            # 根据置信度决定下一步
            if confidence >= self.CONFIDENCE_HIGH:
                result["action"] = "highlight"  # 直接高亮
            elif confidence >= self.CONFIDENCE_MEDIUM:
                result["action"] = "annotate"   # 降级到截图标注
            else:
                result["action"] = "annotate"   # 全部降级

            return json.dumps(result, ensure_ascii=False)

        except Exception as e:
            logger.error("视觉定位失败", error=str(e))
            return json.dumps({
                "error": f"视觉定位失败: {str(e)}",
                "confidence": 0,
                "action": "annotate",
            })


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
visual_locate_tool = VisualLocateTool()
