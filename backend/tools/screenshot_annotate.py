"""
求问 — 截图标注工具
===================

职责：
  - 在截图上绘制标注（红圈、箭头、文字）
  - 使用 Pillow 进行图像处理
  - 返回标注后的图片 base64

标注样式：
  - 红色圆圈：圈出目标元素
  - 红色箭头：指向目标元素
  - 文字说明：在标注旁显示操作说明

用法（Agent 工具调用）：
  result = await annotate_tool.execute(image_base64, 100, 200, 80, 30, "点击这里")
"""

import base64
import io
import json
from dataclasses import dataclass

import structlog
from PIL import Image, ImageDraw, ImageFont

logger = structlog.get_logger()


@dataclass
class ScreenshotAnnotateTool:
    """
    截图标注工具。

    使用 Pillow 在截图上绘制标注。
    """

    name: str = "screenshot_annotate"
    description: str = (
        "在截图上标注目标元素（画红圈/箭头/文字）。"
        "当视觉定位置信度不高时，作为最终降级方案。"
    )
    schema: dict = None

    # 标注样式常量
    CIRCLE_COLOR = (220, 53, 69)      # 红色
    CIRCLE_WIDTH = 3
    ARROW_COLOR = (220, 53, 69)
    TEXT_COLOR = (255, 255, 255)
    TEXT_BG_COLOR = (220, 53, 69)

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "image_base64": {
                        "type": "string",
                        "description": "原始截图的 base64 编码",
                    },
                    "x": {
                        "type": "integer",
                        "description": "目标元素左上角 X 坐标",
                    },
                    "y": {
                        "type": "integer",
                        "description": "目标元素左上角 Y 坐标",
                    },
                    "w": {
                        "type": "integer",
                        "description": "目标元素宽度",
                    },
                    "h": {
                        "type": "integer",
                        "description": "目标元素高度",
                    },
                    "text": {
                        "type": "string",
                        "description": "标注文字说明",
                    },
                },
                "required": ["image_base64", "x", "y", "w", "h", "text"],
            },
        }

    async def execute(
        self,
        image_base64: str,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str,
    ) -> str:
        """
        在截图上绘制标注。

        Args:
            image_base64: 原始截图 base64
            x, y: 目标元素左上角坐标
            w, h: 目标元素宽高
            text: 标注文字

        Returns:
            JSON 字符串：
              {"annotated_image": "base64...", "format": "png"}
        """
        try:
            # 解码截图
            if image_base64.startswith("data:"):
                image_base64 = image_base64.split(",", 1)[1]
            img_bytes = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_bytes))
            draw = ImageDraw.Draw(img)

            # --- 绘制红圈 ---
            padding = 8
            draw.ellipse(
                [x - padding, y - padding, x + w + padding, y + h + padding],
                outline=self.CIRCLE_COLOR,
                width=self.CIRCLE_WIDTH,
            )

            # --- 绘制箭头（从上方指向目标） ---
            arrow_start = (x + w // 2, y - 40)
            arrow_end = (x + w // 2, y - padding)
            draw.line([arrow_start, arrow_end], fill=self.ARROW_COLOR, width=3)
            # 箭头头部
            draw.polygon(
                [
                    (arrow_end[0] - 8, arrow_end[1] - 10),
                    arrow_end,
                    (arrow_end[0] + 8, arrow_end[1] - 10),
                ],
                fill=self.ARROW_COLOR,
            )

            # --- 绘制文字标签 ---
            if text:
                # 尝试加载字体（系统字体，失败则用默认）
                try:
                    font = ImageFont.truetype("msyh.ttc", 16)  # 微软雅黑
                except OSError:
                    try:
                        font = ImageFont.truetype("arial.ttf", 16)
                    except OSError:
                        font = ImageFont.load_default()

                # 计算文字大小
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                # 绘制文字背景
                label_x = x + w // 2 - text_w // 2 - 8
                label_y = y - 60
                draw.rectangle(
                    [label_x, label_y, label_x + text_w + 16, label_y + text_h + 8],
                    fill=self.TEXT_BG_COLOR,
                )
                # 绘制文字
                draw.text(
                    (label_x + 8, label_y + 4),
                    text,
                    fill=self.TEXT_COLOR,
                    font=font,
                )

            # 编码为 base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            annotated_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            logger.info("截图标注完成", text=text, x=x, y=y, w=w, h=h)
            return json.dumps(
                {"annotated_image": annotated_base64, "format": "png"},
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error("截图标注失败", error=str(e))
            return json.dumps({"error": f"标注失败: {str(e)}"})


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
screenshot_annotate_tool = ScreenshotAnnotateTool()
