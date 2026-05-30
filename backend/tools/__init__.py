"""
求问 — 工具集注册表
===================

职责：
  - 收集所有 Agent 可调用的工具
  - 提供 Function Calling schema（供 LLM 理解工具用法）
  - 提供工具实例列表（供 Agent 执行调用）

工具清单（Phase 1）：
  search_docs       — 混合检索本地文档（Chroma + BM25 + RRF）
  fetch_doc_page    — 抓取远程页面正文（httpx + trafilatura）
  save_memory       — 保存长期记忆
  recall_memory     — 回忆长期记忆

工具清单（Phase 2 新增）：
  highlight_element — 在页面上高亮元素
  visual_locate     — 截图视觉定位
  screenshot_annotate — 截图标注

工具清单（Phase 3 新增）：
  classify_page     — 页面类型分类
  learn_flow        — 操作流录制/回放

用法：
  from tools import get_all_tools, get_tool_schemas
  tools = get_all_tools()       # 工具实例列表
  schemas = get_tool_schemas()  # Function Calling schema 列表
"""

from tools.search_docs import search_docs_tool
from tools.fetch_doc_page import fetch_doc_page_tool
from tools.memory_tools import save_memory_tool, recall_memory_tool

__all__ = ["get_all_tools", "get_tool_schemas"]


# ---------------------------------------------------------------------------
# 工具实例注册表
# ---------------------------------------------------------------------------
# 新增工具时，只需：
#   1. 在对应模块中创建 xxx_tool 实例
#   2. 在此处 import 并添加到 _ALL_TOOLS
_ALL_TOOLS = [
    search_docs_tool,
    fetch_doc_page_tool,
    save_memory_tool,
    recall_memory_tool,
]


def get_all_tools() -> list:
    """
    返回所有工具实例。

    用途：
      - Agent 执行工具调用时，根据工具名查找对应实例
      - tools/__init__.py 中的 execute() 方法是实际执行入口
    """
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    """
    返回所有工具的 Function Calling schema。

    用途：
      - 传给 LLM 的 tools 参数，让 LLM 知道有哪些工具可用
      - schema 格式遵循 OpenAI Function Calling 规范

    示例返回值：
      [
        {
          "name": "search_docs",
          "description": "从本地文档索引中搜索相关信息...",
          "parameters": {"type": "object", "properties": {...}, "required": [...]}
        },
        ...
      ]
    """
    return [tool.schema for tool in _ALL_TOOLS]
