"""
求问 — MCP Server
=================

让求问成为 MCP (Model Context Protocol) 工具服务器，
供其他 AI Agent（如 Claude Desktop、Cursor）调用。

协议：MCP (Model Context Protocol) by Anthropic
传输：stdio（标准输入输出）

暴露的工具：
  - search_docs: 从本地文档索引搜索
  - fetch_page: 抓取页面正文
  - guide_element: 在页面上引导操作
  - classify_page: 判断页面类型

用法：
  # 直接运行（stdio 模式）
  python -m mcp.server

  # 在 Claude Desktop 中配置
  {
    "mcpServers": {
      "qiuwen": {
        "command": "python",
        "args": ["-m", "mcp.server"],
        "cwd": "/path/to/backend"
      }
    }
  }
"""

import asyncio
import json
import sys
from pathlib import Path

# 确保 backend 目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger()


def create_server():
    """创建并配置 MCP Server。"""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.error("mcp 包未安装，请运行: pip install mcp")
        sys.exit(1)

    mcp = FastMCP("qiuwen", instructions="求问 — 本地智能网页引导助手。可以搜索本地文档、抓取页面、引导操作。")

    # -----------------------------------------------------------------------
    # 工具：文档搜索
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def search_docs(query: str, top_k: int = 5) -> str:
        """
        从本地文档索引中搜索相关信息。

        当用户问关于产品使用、操作步骤、功能说明等问题时调用。

        Args:
            query: 搜索查询文本，应包含核心关键词
            top_k: 返回结果数量，默认 5
        """
        from tools.search_docs import SearchDocsTool
        from memory.long_term import LongTermMemory

        tool = SearchDocsTool()
        memory = LongTermMemory()
        try:
            await memory.initialize()
            result = await tool.execute(query=query, top_k=top_k, long_term_memory=memory)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        finally:
            await memory.close()

    # -----------------------------------------------------------------------
    # 工具：页面抓取
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def fetch_page(url: str) -> str:
        """
        获取指定 URL 的页面正文内容。

        当需要查看具体文档页面、或 search_docs 结果不够详细时调用。

        Args:
            url: 要抓取的页面 URL（必须是完整的 http/https 地址）
        """
        from tools.fetch_doc_page import FetchDocPageTool

        tool = FetchDocPageTool()
        try:
            result = await tool.execute(url=url)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 工具：元素引导
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def guide_element(selector: str, description: str, page_url: str = "") -> str:
        """
        在页面上高亮指定元素，引导用户操作。

        当需要告诉用户某个按钮/链接在哪里时调用。

        Args:
            selector: 目标元素的 CSS 选择器（如 '#create-btn', '.submit-button'）
            description: 对这个元素的描述（如 '创建项目按钮'）
            page_url: 当前页面 URL（用于指纹查找/存储）
        """
        from tools.highlight_element import HighlightElementTool
        from memory.fingerprint_storage import get_fingerprint_storage

        tool = HighlightElementTool()
        storage = get_fingerprint_storage()
        try:
            result = await tool.execute(
                selector=selector,
                description=description,
                page_url=page_url,
                fingerprint_storage=storage,
            )
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 工具：页面分类
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def classify_page(url: str, dom_snapshot: str = "") -> str:
        """
        判断当前页面的类型（表单/列表/详情/仪表盘/编辑器等）。

        用于辅助操作引导，不同页面类型有不同的引导策略。

        Args:
            url: 当前页面 URL
            dom_snapshot: 页面 DOM 快照（可选，提高准确度）
        """
        from tools.classify_page import ClassifyPageTool

        tool = ClassifyPageTool()
        try:
            result = await tool.execute(url=url, dom_snapshot=dom_snapshot)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 工具：浏览器快照
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def browser_snapshot(interactive_only: bool = True, selector: str = "", max_depth: int = 15) -> str:
        """
        获取当前页面的无障碍树快照。

        返回 @eN 引用格式的元素树，AI 可直接用 @eN 调用 browser_interact 操作元素。
        参考 agent-browser 的 snapshot 命令。

        Args:
            interactive_only: 只返回交互元素（推荐）
            selector: 限定 CSS 选择器范围
            max_depth: 最大遍历深度
        """
        from tools.browser_tools import BrowserSnapshotTool
        tool = BrowserSnapshotTool()
        try:
            return await tool.execute(
                interactive_only=interactive_only,
                selector=selector,
                max_depth=max_depth,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 工具：浏览器交互
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def browser_interact(ref: str, action: str, value: str = "") -> str:
        """
        与页面元素交互。使用 @eN 引用（从 browser_snapshot 获取）指定目标元素。

        支持：click/dblclick/hover/focus/fill/type/check/uncheck/select/scroll

        Args:
            ref: 元素引用（如 @e1, @e5）
            action: 操作类型
            value: 填写值（fill/type/select 时使用）
        """
        from tools.browser_tools import BrowserInteractTool
        tool = BrowserInteractTool()
        try:
            return await tool.execute(ref=ref, action=action, value=value)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 工具：语义查找
    # -----------------------------------------------------------------------
    @mcp.tool()
    async def browser_find(strategy: str, value: str, exact: bool = False, name: str = "") -> str:
        """
        按语义定位页面元素。不需要先 snapshot，直接用角色/文本/标签等查找。

        Args:
            strategy: 查找策略 (role/text/label/placeholder/testid)
            value: 查找值（如 'button', 'Sign In', 'Email'）
            exact: 精确匹配
            name: 附加名称过滤（role 策略时使用）
        """
        from tools.browser_tools import BrowserFindTool
        tool = BrowserFindTool()
        try:
            return await tool.execute(strategy=strategy, value=value, exact=exact, name=name)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 资源：系统状态
    # -----------------------------------------------------------------------
    @mcp.resource("qiuwen://status")
    async def system_status() -> str:
        """求问系统状态。"""
        return json.dumps({
            "name": "求问",
            "version": "0.1.0",
            "description": "本地智能网页引导助手",
            "tools": [
                "search_docs", "fetch_page", "guide_element", "classify_page",
                "browser_snapshot", "browser_interact", "browser_find",
            ],
        }, ensure_ascii=False)

    return mcp


def main():
    """启动 MCP Server（stdio 模式）。"""
    mcp = create_server()
    logger.info("求问 MCP Server 启动中...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
