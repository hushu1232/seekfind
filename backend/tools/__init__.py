"""
求问 — 工具集注册表
===================

工具清单：
  Phase 1（核心）：
    search_docs          — 混合检索本地文档
    fetch_doc_page       — 抓取远程页面正文
    save_memory          — 保存长期记忆
    recall_memory        — 回忆长期记忆

  Phase 2（视觉引导）：
    highlight_element    — 在页面上高亮元素
    visual_locate        — 截图视觉定位
    screenshot_annotate  — 截图标注

  Phase 3（交互体验）：
    classify_page        — 页面类型分类
    learn_flow           — 操作流录制/回放
"""

from tools.search_docs import search_docs_tool
from tools.fetch_doc_page import fetch_doc_page_tool
from tools.memory_tools import save_memory_tool, recall_memory_tool
from tools.highlight_element import highlight_element_tool
from tools.visual_locate import visual_locate_tool
from tools.screenshot_annotate import screenshot_annotate_tool
from tools.classify_page import classify_page_tool
from tools.learn_flow import learn_flow_tool

__all__ = ["get_all_tools", "get_tool_schemas"]


_ALL_TOOLS = [
    # Phase 1
    search_docs_tool,
    fetch_doc_page_tool,
    save_memory_tool,
    recall_memory_tool,
    # Phase 2
    highlight_element_tool,
    visual_locate_tool,
    screenshot_annotate_tool,
    # Phase 3
    classify_page_tool,
    learn_flow_tool,
]


def get_all_tools() -> list:
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    return [tool.schema for tool in _ALL_TOOLS]
