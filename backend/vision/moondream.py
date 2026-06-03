"""
求问 — moondream2 视觉定位模块
==============================

职责：
  - 加载 moondream2 轻量视觉模型（1.6B 参数）
  - 在截图中定位目标元素，返回坐标和置信度
  - 在截图上标注（红圈/箭头/文字）

模型选择理由：
  - moondream2 仅 1.6B 参数，可在 CPU 上运行
  - 支持视觉问答（VQA），适合元素定位任务
  - 推理速度快（< 1 秒），适合实时引导

加载方式：
  - 优先使用 Ollama 加载（如果 ollama 支持 moondream2）
  - 备选：直接使用 transformers 加载本地模型

用法：
  vision = MoondreamVision()
  await vision.initialize()
  result = await vision.locate_element(image_base64, "创建按钮")
  annotated = await vision.annotate_screenshot(image_base64, x, y, w, h)
"""

import base64
import io
import json

import structlog
from PIL import Image, ImageDraw, ImageFont

logger = structlog.get_logger()


class MoondreamVision:
    """
    moondream2 视觉模型封装。

    支持两种运行模式：
      1. Ollama 模式：通过 Ollama API 调用（推荐，自动管理模型生命周期）
      2. 本地模式：直接加载模型文件（备选，需要更多显存）

    属性：
      _model: 模型实例（本地模式）
      _use_ollama: 是否使用 Ollama 模式
      _ollama_url: Ollama API 地址
    """

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self._model = None
        self._use_ollama = True
        self._ollama_url = ollama_url

    async def initialize(self) -> None:
        """
        初始化视觉模型。

        优先尝试 Ollama，失败则回退到本地 transformers。
        """
        # 尝试 Ollama 模式
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._ollama_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    has_moondream = any("moondream" in m.get("name", "") for m in models)
                    if has_moondream:
                        self._use_ollama = True
                        logger.info("视觉模型：使用 Ollama moondream2")
                        return
                    else:
                        logger.info("Ollama 中未找到 moondream2，尝试拉取...")
                        # 尝试拉取
                        pull_resp = await client.post(
                            f"{self._ollama_url}/api/pull",
                            json={"name": "moondream2"},
                            timeout=120,
                        )
                        if pull_resp.status_code == 200:
                            self._use_ollama = True
                            logger.info("moondream2 拉取成功")
                            return
        except Exception as e:
            logger.warning("Ollama 模式初始化失败", error=str(e))

        # 回退到本地 transformers 模式
        self._use_ollama = False
        logger.info("视觉模型：使用本地 transformers 模式")
        # TODO: 本地 transformers 加载（需要下载模型文件）
        # from transformers import AutoModelForCausalLM
        # self._model = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2")

    async def locate_element(
        self, image_base64: str, description: str
    ) -> dict:
        """
        在截图中定位元素。

        Args:
            image_base64: 截图的 base64 编码
            description: 要定位的元素描述

        Returns:
            {
                "x": int,        # 元素左上角 X 坐标
                "y": int,        # 元素左上角 Y 坐标
                "w": int,        # 元素宽度
                "h": int,        # 元素高度
                "confidence": float  # 置信度 (0-1)
            }
        """
        if self._use_ollama:
            return await self._locate_via_ollama(image_base64, description)
        else:
            return await self._locate_via_local(image_base64, description)

    async def _locate_via_ollama(
        self, image_base64: str, description: str
    ) -> dict:
        """通过 Ollama API 调用 moondream2 定位。"""
        import httpx

        prompt = (
            f"Find the UI element described as '{description}' in this screenshot. "
            f"Return its bounding box as JSON: {{\"x\": int, \"y\": int, \"w\": int, \"h\": int}}. "
            f"If you cannot find it, return {{\"x\": 0, \"y\": 0, \"w\": 0, \"h\": 0}}"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/generate",
                    json={
                        "model": "moondream2",
                        "prompt": prompt,
                        "images": [image_base64],
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                result_text = resp.json().get("response", "")

                # 解析 JSON 响应
                return self._parse_location_response(result_text)

        except Exception as e:
            logger.error("Ollama 视觉定位失败", error=str(e))
            return {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0}

    async def _locate_via_local(
        self, image_base64: str, description: str
    ) -> dict:
        """通过本地模型定位（备用方案）。"""
        if not self._model:
            logger.warning("本地视觉模型未加载")
            return {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0}

        # TODO: 本地模型推理
        logger.info("本地视觉定位（待实现）", description=description)
        return {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0}

    def _parse_location_response(self, text: str) -> dict:
        """解析模型返回的坐标 JSON。"""
        try:
            # 尝试从回复中提取 JSON
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(text[json_start:json_end])
                # 计算置信度（基于返回值是否全为 0）
                x, y, w, h = data.get("x", 0), data.get("y", 0), data.get("w", 0), data.get("h", 0)
                confidence = 0.0 if x == 0 and y == 0 and w == 0 and h == 0 else 0.8
                return {"x": x, "y": y, "w": w, "h": h, "confidence": confidence}
        except (json.JSONDecodeError, KeyError):
            pass

        return {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0}

    async def annotate_screenshot(
        self,
        image_base64: str,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str = "",
    ) -> str:
        """
        在截图上标注（红圈/箭头/文字）。

        Args:
            image_base64: 原始截图 base64
            x, y: 目标元素左上角坐标
            w, h: 目标元素宽高
            text: 标注文字

        Returns:
            标注后的图片 base64
        """
        try:
            # 解码截图
            if image_base64.startswith("data:"):
                image_base64 = image_base64.split(",", 1)[1]
            img_bytes = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_bytes))
            draw = ImageDraw.Draw(img)

            # 红圈
            padding = 8
            draw.ellipse(
                [x - padding, y - padding, x + w + padding, y + h + padding],
                outline=(220, 53, 69),
                width=3,
            )

            # 箭头
            arrow_start = (x + w // 2, y - 40)
            arrow_end = (x + w // 2, y - padding)
            draw.line([arrow_start, arrow_end], fill=(220, 53, 69), width=3)
            draw.polygon(
                [
                    (arrow_end[0] - 8, arrow_end[1] - 10),
                    arrow_end,
                    (arrow_end[0] + 8, arrow_end[1] - 10),
                ],
                fill=(220, 53, 69),
            )

            # 文字标签
            if text:
                try:
                    font = ImageFont.truetype("msyh.ttc", 16)
                except OSError:
                    font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                label_x = x + w // 2 - text_w // 2 - 8
                label_y = y - 60
                draw.rectangle(
                    [label_x, label_y, label_x + text_w + 16, label_y + 24],
                    fill=(220, 53, 69),
                )
                draw.text((label_x + 8, label_y + 4), text, fill=(255, 255, 255), font=font)

            # 编码
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

        except Exception as e:
            logger.error("截图标注失败", error=str(e))
            return image_base64
