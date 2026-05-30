"""
求问 — 工具集注册表
收集所有工具的 Function Calling schema，供 Agent 使用。
"""

from tools.search_docs import search_docs_tool
from tools.fetch_doc_page import fetch_doc_page_tool
from tools.memory_tools import save_memory_tool, recall_memory_tool

__all__ = ["get_all_tools", "get_tool_schemas"]


# 所有工具实例
_ALL_TOOLS = [
    search_docs_tool,
    fetch_doc_page_tool,
    save_memory_tool,
    recall_memory_tool,
]


def get_all_tools() -> list:
    """返回所有工具实例。"""
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 Function Calling schema。"""
    return [tool.schema for tool in _ALL_TOOLS]
