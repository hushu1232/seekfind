"""
求问 — 浏览器控制器
==================

通过 WebSocket 与 Chrome Extension Content Script 通信，
实现无障碍树快照、语义定位、元素交互。

架构：
  后端工具 → WS 请求 → Service Worker → Content Script → DOM 操作 → WS 响应

请求-响应模式：
  1. 工具调用 controller.snapshot()
  2. controller 发送 WS 消息 {"type": "browser_snapshot", "req_id": "xxx"}
  3. 等待 Content Script 返回 {"type": "snapshot_result", "req_id": "xxx", ...}
  4. 返回结果给工具

参考 agent-browser 的核心循环：
  open → snapshot → @eN → click → snapshot → ...
"""

import asyncio
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()


class BrowserController:
    """
    浏览器控制器。

    通过 WebSocket 与 Chrome Extension Content Script 通信。
    """

    def __init__(self):
        # req_id → asyncio.Future 映射
        self._pending: dict[str, asyncio.Future] = {}
        # 活跃的 WebSocket 连接
        self._ws: Any = None

    def set_ws(self, ws: Any) -> None:
        """设置当前 WebSocket 连接。"""
        self._ws = ws

    async def _send_and_wait(self, msg_type: str, payload: dict, timeout: float = 10) -> dict:
        """
        发送 WS 消息并等待响应。

        Args:
            msg_type: 消息类型
            payload: 消息负载
            timeout: 超时秒数

        Returns:
            响应数据
        """
        if not self._ws:
            return {"error": "浏览器未连接"}

        req_id = str(uuid.uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            await self._ws.send_json({
                "type": msg_type,
                "req_id": req_id,
                **payload,
            })

            # 等待响应
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except TimeoutError:
            logger.warning("浏览器控制超时", msg_type=msg_type, req_id=req_id)
            return {"error": f"超时（{timeout}秒）"}
        except Exception as e:
            logger.error("浏览器控制失败", msg_type=msg_type, error=str(e))
            return {"error": str(e)}
        finally:
            self._pending.pop(req_id, None)

    def handle_response(self, msg: dict) -> bool:
        """
        处理来自 Content Script 的响应。

        Returns:
            True 如果消息被处理，False 如果不是响应消息
        """
        req_id = msg.get("req_id")
        if not req_id or req_id not in self._pending:
            return False

        future = self._pending[req_id]
        if not future.done():
            future.set_result(msg)
        return True

    # -----------------------------------------------------------------------
    # 公开 API
    # -----------------------------------------------------------------------

    async def snapshot(
        self,
        interactive_only: bool = True,
        selector: str = "",
        max_depth: int = 15,
    ) -> dict:
        """
        获取页面无障碍树快照。

        参考 agent-browser: `agent-browser snapshot -i`

        Args:
            interactive_only: 只返回交互元素（推荐）
            selector: 限定 CSS 选择器范围
            max_depth: 最大遍历深度

        Returns:
            {"text": "快照文本", "refCount": 5, "url": "...", "title": "..."}
        """
        return await self._send_and_wait("qiuwen:snapshot", {
            "options": {
                "interactiveOnly": interactive_only,
                "selector": selector,
                "maxDepth": max_depth,
            }
        })

    async def find(
        self,
        strategy: str,
        value: str,
        exact: bool = False,
        name: str = "",
    ) -> dict:
        """
        语义定位元素。

        参考 agent-browser: `agent-browser find role button --name "Submit"`

        Args:
            strategy: 查找策略 (role/text/label/placeholder/testid)
            value: 查找值
            exact: 精确匹配
            name: 附加名称过滤（role 策略时使用）

        Returns:
            {"ref": "@e3", "strategy": "role", "value": "button"}
        """
        return await self._send_and_wait("qiuwen:find_element", {
            "strategy": strategy,
            "value": value,
            "options": {"exact": exact, "name": name},
        })

    async def interact(
        self,
        ref: str,
        action: str,
        value: str = "",
    ) -> dict:
        """
        与页面元素交互。

        参考 agent-browser:
          - `agent-browser click @e1`
          - `agent-browser fill @e2 "hello"`
          - `agent-browser select @e3 "option"`

        Args:
            ref: @eN 引用
            action: 操作类型 (click/dblclick/hover/focus/fill/type/check/uncheck/select/scroll)
            value: 填写值（fill/type/select 时使用）

        Returns:
            {"success": true} 或 {"success": false, "error": "..."}
        """
        return await self._send_and_wait("qiuwen:execute_interaction", {
            "ref": ref,
            "action": action,
            "value": value,
        })

    async def click(self, ref: str) -> dict:
        """点击元素。"""
        return await self.interact(ref, "click")

    async def fill(self, ref: str, value: str) -> dict:
        """填写输入框。"""
        return await self.interact(ref, "fill", value)

    async def type_text(self, ref: str, value: str) -> dict:
        """追加输入。"""
        return await self.interact(ref, "type", value)

    async def hover(self, ref: str) -> dict:
        """悬停元素。"""
        return await self.interact(ref, "hover")

    async def focus(self, ref: str) -> dict:
        """聚焦元素。"""
        return await self.interact(ref, "focus")

    async def scroll_into_view(self, ref: str) -> dict:
        """滚动元素到可见区域。"""
        return await self.interact(ref, "scroll")

    async def select(self, ref: str, value: str) -> dict:
        """选择下拉框选项。"""
        return await self.interact(ref, "select", value)

    async def check(self, ref: str) -> dict:
        """勾选复选框。"""
        return await self.interact(ref, "check")

    async def uncheck(self, ref: str) -> dict:
        """取消勾选。"""
        return await self.interact(ref, "uncheck")


# 全局单例
browser_controller = BrowserController()
