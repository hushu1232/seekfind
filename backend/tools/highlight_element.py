"""
求问 — 高亮元素工具
===================

职责：
  - 根据 selector/xpath 定位页面元素
  - 计算元素的屏幕坐标 (rect)
  - 通过 WebSocket 下发高亮指令到 Content Script

定位优先级（强化后）：
  0. 指纹库查找（<10ms，命中率高时优先）
  1. CSS selector（最快，最精确）
  2. XPath（selector 失败时的备选）
  3. 元素指纹库匹配（已知页面的元素映射）

指纹闭环：
  - 定位成功后自动存储指纹到 SQLite
  - 下次相同 URL + 相似描述直接命中缓存
  - 参考 Scrapling 的 StorageSystemMixin 设计

用法（Agent 工具调用）：
  result = await highlight_tool.execute("#create-btn", "点击创建按钮", "https://github.com/dashboard")

输出（WS 消息）：
  {"type": "highlight", "selector": "#create-btn", "description": "点击创建按钮", "order": 1}
"""

import json
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()


@dataclass
class HighlightElementTool:
    """
    高亮元素工具。

    注意：此工具不直接操作 DOM，而是生成高亮指令，
    由 Service Worker 路由到 Content Script 执行。
    """

    name: str = "highlight_element"
    description: str = (
        "在页面上高亮指定元素，引导用户注意。"
        "当需要告诉用户某个按钮/链接在哪里时调用。"
    )
    schema: dict = None
    _fingerprint_storage: object = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": (
                            "目标元素的 CSS 选择器（如 '#create-btn', '.submit-button'）。"
                            "如果不确定，传 'auto' 让系统从指纹库查找。"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "对这个元素的描述（如 '创建项目按钮'）",
                    },
                    "page_url": {
                        "type": "string",
                        "description": "当前页面 URL（用于指纹查找/存储）",
                    },
                    "fallback_selector": {
                        "type": "string",
                        "description": "备选选择器（主选择器失败时使用）",
                    },
                    "order": {
                        "type": "integer",
                        "description": "步骤序号（多步指引时使用）",
                        "default": 1,
                    },
                    "style": {
                        "type": "string",
                        "description": "高亮样式：pulse（脉冲）/ glow（发光）/ arrow（箭头）",
                        "enum": ["pulse", "glow", "arrow"],
                        "default": "pulse",
                    },
                },
                "required": ["selector", "description", "page_url"],
            },
        }

    async def execute(
        self,
        selector: str,
        description: str,
        page_url: str = "",
        fallback_selector: str = None,
        order: int = 1,
        style: str = "pulse",
        fingerprint_storage=None,
    ) -> str:
        """
        生成高亮指令。

        此工具不直接操作 DOM，而是返回一个高亮指令 JSON，
        由 Agent 的 stream_reply 方法捕获并通过 WS 下发。

        指纹闭环：
          1. 如果 selector 为 "auto"，先查指纹库
          2. 定位成功后自动存储指纹

        Args:
            selector: CSS 选择器（传 "auto" 时从指纹库查找）
            description: 元素描述
            page_url: 当前页面 URL
            fallback_selector: 备选选择器
            order: 步骤序号
            style: 高亮样式
            fingerprint_storage: FingerprintStorage 实例（由 Agent 注入）

        Returns:
            JSON 字符串，包含高亮指令
        """
        storage = fingerprint_storage or self._fingerprint_storage

        # Layer 0: 指纹库查找（selector 为空或 "auto" 时）
        if storage and page_url and (not selector or selector == "auto"):
            fp = storage.find(page_url, description)
            if fp:
                selector = fp["selector"]
                fallback_selector = fallback_selector or fp.get("xpath") or ""
                logger.info(
                    "指纹命中，使用缓存 selector",
                    selector=selector,
                    desc=description,
                    success_count=fp.get("success_count", 0),
                )

        # 校验 selector
        if not selector or selector == "auto":
            logger.warning("未找到有效 selector", desc=description)
            return json.dumps({
                "error": f"未找到「{description}」的定位方式，请尝试视觉定位",
                "selector": None,
                "description": description,
            }, ensure_ascii=False)

        logger.info(
            "生成高亮指令",
            selector=selector,
            description=description,
            order=order,
            style=style,
        )

        # 自动存储指纹（成功定位后）
        if storage and page_url and selector and selector != "auto":
            try:
                normalized_url = self._normalize_url(page_url)
                storage.save(
                    url_pattern=normalized_url,
                    selector=selector,
                    description=description,
                    xpath=fallback_selector or "",
                )
            except Exception as e:
                logger.debug("指纹存储失败（不影响主流程）", error=str(e))

        return json.dumps(
            {
                "action": "highlight",
                "selector": selector,
                "fallback_selector": fallback_selector,
                "description": description,
                "order": order,
                "style": style,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        """URL 归一化：去掉查询参数和锚点，保留域名+路径。"""
        try:
            parsed = urlparse(url)
            return f"{parsed.netloc}{parsed.path}".rstrip("/")
        except Exception:
            return url


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
highlight_element_tool = HighlightElementTool()
