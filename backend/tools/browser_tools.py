"""
求问 — 浏览器控制工具集
======================

参考 agent-browser 的核心能力，为 Agent 提供浏览器控制工具：

  browser_snapshot: 获取页面无障碍树快照（@eN 引用格式）
  browser_interact: 与页面元素交互（click/fill/hover/select 等）
  browser_find: 语义定位元素（role/text/label/placeholder）

输出格式（参考 agent-browser）：
  @e1 [heading] "Log in"
  @e2 [form]
    @e3 [textbox] placeholder="Email"
    @e4 [button] "Continue"

与 highlight_element 的区别：
  - highlight_element: 生成高亮指令，由前端渲染
  - browser_snapshot: 获取页面结构，供 AI 理解
  - browser_interact: 直接操作页面元素
"""

import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class BrowserSnapshotTool:
    """
    获取页面无障碍树快照。

    参考 agent-browser: `agent-browser snapshot -i`

    输出紧凑的 @eN 引用格式，AI 可直接用 @eN 操作元素。
    """

    name: str = "browser_snapshot"
    description: str = (
        "获取当前页面的无障碍树快照。"
        "返回 @eN 引用格式的元素树，AI 可直接用 @eN 调用 browser_interact 操作元素。"
        "参考 agent-browser 的 snapshot 命令。"
    )
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "interactive_only": {
                        "type": "boolean",
                        "description": "只返回交互元素（推荐），默认 true",
                        "default": True,
                    },
                    "selector": {
                        "type": "string",
                        "description": "限定 CSS 选择器范围（可选）",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "最大遍历深度，默认 15",
                        "default": 15,
                    },
                },
                "required": [],
            },
        }

    async def execute(
        self,
        interactive_only: bool = True,
        selector: str = "",
        max_depth: int = 15,
        browser_controller=None,
    ) -> str:
        """
        获取页面快照。

        Args:
            interactive_only: 只返回交互元素
            selector: CSS 选择器范围
            max_depth: 最大深度
            browser_controller: BrowserController 实例

        Returns:
            JSON: {"text": "快照文本", "refCount": 5, "url": "...", "title": "..."}
        """
        if not browser_controller:
            return json.dumps({"error": "浏览器未连接"})

        result = await browser_controller.snapshot(
            interactive_only=interactive_only,
            selector=selector,
            max_depth=max_depth,
        )

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "snapshot": result.get("text", ""),
            "ref_count": result.get("refCount", 0),
            "url": result.get("url", ""),
            "title": result.get("title", ""),
        }, ensure_ascii=False)


@dataclass
class BrowserInteractTool:
    """
    与页面元素交互。

    参考 agent-browser:
      - `agent-browser click @e1`
      - `agent-browser fill @e2 "hello"`
      - `agent-browser hover @e3`
    """

    name: str = "browser_interact"
    description: str = (
        "与页面元素交互。使用 @eN 引用（从 browser_snapshot 获取）指定目标元素。"
        "支持：click/dblclick/hover/focus/fill/type/check/uncheck/select/scroll。"
    )
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "元素引用（如 @e1, @e5），从 browser_snapshot 获取",
                    },
                    "action": {
                        "type": "string",
                        "description": "操作类型",
                        "enum": ["click", "dblclick", "hover", "focus", "fill", "type", "check", "uncheck", "select", "scroll"],
                    },
                    "value": {
                        "type": "string",
                        "description": "填写值（fill/type/select 时使用）",
                    },
                },
                "required": ["ref", "action"],
            },
        }

    async def execute(
        self,
        ref: str,
        action: str,
        value: str = "",
        browser_controller=None,
    ) -> str:
        """
        执行交互操作。

        Args:
            ref: @eN 引用
            action: 操作类型
            value: 填写值
            browser_controller: BrowserController 实例

        Returns:
            JSON: {"success": true} 或 {"success": false, "error": "..."}
        """
        if not browser_controller:
            return json.dumps({"error": "浏览器未连接"})

        result = await browser_controller.interact(ref, action, value)

        if "error" in result:
            return json.dumps({"success": False, "error": result["error"]})

        return json.dumps({
            "success": result.get("success", False),
            "ref": ref,
            "action": action,
            "error": result.get("error"),
        }, ensure_ascii=False)


@dataclass
class BrowserFindTool:
    """
    语义定位元素。

    参考 agent-browser: `agent-browser find role button --name "Submit"`
    """

    name: str = "browser_find"
    description: str = (
        "按语义定位页面元素。不需要先 snapshot，直接用角色/文本/标签等查找。"
        "返回匹配元素的 @eN 引用。"
    )
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "string",
                        "description": "查找策略",
                        "enum": ["role", "text", "label", "placeholder", "testid"],
                    },
                    "value": {
                        "type": "string",
                        "description": "查找值（如 'button', 'Sign In', 'Email'）",
                    },
                    "exact": {
                        "type": "boolean",
                        "description": "精确匹配，默认 false",
                        "default": False,
                    },
                    "name": {
                        "type": "string",
                        "description": "附加名称过滤（role 策略时使用）",
                    },
                },
                "required": ["strategy", "value"],
            },
        }

    async def execute(
        self,
        strategy: str,
        value: str,
        exact: bool = False,
        name: str = "",
        browser_controller=None,
    ) -> str:
        """
        语义查找元素。

        Args:
            strategy: 查找策略
            value: 查找值
            exact: 精确匹配
            name: 附加名称
            browser_controller: BrowserController 实例

        Returns:
            JSON: {"ref": "@e3", "strategy": "role", "value": "button"}
        """
        if not browser_controller:
            return json.dumps({"error": "浏览器未连接"})

        result = await browser_controller.find(strategy, value, exact, name)

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "ref": result.get("ref"),
            "strategy": strategy,
            "value": value,
            "found": result.get("ref") is not None,
        }, ensure_ascii=False)


# 工具实例
browser_snapshot_tool = BrowserSnapshotTool()
browser_interact_tool = BrowserInteractTool()
browser_find_tool = BrowserFindTool()
