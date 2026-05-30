"""
求问 — 工具集注册表
===================

工具清单：
  Phase 1（核心）：
    search_docs          — 混合检索本地文档（Chroma + BM25 + RRF）
    fetch_doc_page       — 抓取远程页面正文（httpx + trafilatura）
    save_memory          — 保存长期记忆
    recall_memory        — 回忆长期记忆

  Phase 2（视觉引导）：
    highlight_element    — 在页面上高亮元素（selector → 高亮指令）
    visual_locate        — 截图视觉定位（moondream2 → 坐标）
    screenshot_annotate  — 截图标注（Pillow → 红圈/箭头）

  Phase 3（交互体验）：
    classify_page        — 页面类型分类（待实现）
    learn_flow           — 操作流录制/回放（待实现）

用法：
  from tools import get_all_tools, get_tool_schemas
  tools = get_all_tools()
  schemas = get_tool_schemas()
"""

from tools.search_docs import search_docs_tool
from tools.fetch_doc_page import fetch_doc_page_tool
from tools.memory_tools import save_memory_tool, recall_memory_tool
from tools.highlight_element import highlight_element_tool
from tools.visual_locate import visual_locate_tool
from tools.screenshot_annotate import screenshot_annotate_tool

__all__ = ["get_all_tools", "get_tool_schemas"]


# ---------------------------------------------------------------------------
# 工具实例注册表
# ---------------------------------------------------------------------------
_ALL_TOOLS = [
    # Phase 1: 核心工具
    search_docs_tool,
    fetch_doc_page_tool,
    save_memory_tool,
    recall_memory_tool,
    # Phase 2: 视觉引导工具
    highlight_element_tool,
    visual_locate_tool,
    screenshot_annotate_tool,
]


def get_all_tools() -> list:
    """返回所有工具实例。"""
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 Function Calling schema。"""
    return [tool.schema for tool in _ALL_TOOLS]
