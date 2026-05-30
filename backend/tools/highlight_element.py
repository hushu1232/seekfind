"""
求问 — 高亮元素工具
===================

职责：
  - 根据 selector/xpath 定位页面元素
  - 计算元素的屏幕坐标 (rect)
  - 通过 WebSocket 下发高亮指令到 Content Script

定位优先级：
  1. CSS selector（最快，最精确）
  2. XPath（selector 失败时的备选）
  3. 元素指纹库匹配（Phase 3：已知页面的元素映射）

用法（Agent 工具调用）：
  result = await highlight_tool.execute("#create-btn", "点击创建按钮")

输出（WS 消息）：
  {"type": "highlight", "selector": "#create-btn", "description": "点击创建按钮", "order": 1}
"""

import json
from dataclasses import dataclass

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

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "目标元素的 CSS 选择器（如 '#create-btn', '.submit-button'）",
                    },
                    "description": {
                        "type": "string",
                        "description": "对这个元素的描述（如 '创建项目按钮'）",
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
                "required": ["selector", "description"],
            },
        }

    async def execute(
        self,
        selector: str,
        description: str,
        fallback_selector: str = None,
        order: int = 1,
        style: str = "pulse",
    ) -> str:
        """
        生成高亮指令。

        此工具不直接操作 DOM，而是返回一个高亮指令 JSON，
        由 Agent 的 stream_reply 方法捕获并通过 WS 下发。

        Args:
            selector: CSS 选择器
            description: 元素描述
            fallback_selector: 备选选择器
            order: 步骤序号
            style: 高亮样式

        Returns:
            JSON 字符串，包含高亮指令
        """
        logger.info(
            "生成高亮指令",
            selector=selector,
            description=description,
            order=order,
            style=style,
        )

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


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
highlight_element_tool = HighlightElementTool()
