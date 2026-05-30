"""
求问 — 工具集注册表
===================

工具清单：
  Phase 1: search_docs, fetch_doc_page, save_memory, recall_memory
  Phase 2: highlight_element, visual_locate, screenshot_annotate
  Phase 3: classify_page, learn_flow

关键设计：
  每个工具同时提供：
    1. xxx_tool 实例 — 自定义 dataclass，有 execute() 方法
    2. xxx_langchain — LangChain StructuredTool，供 ToolNode 使用
"""

from langchain_core.tools import StructuredTool

from tools.search_docs import search_docs_tool
from tools.fetch_doc_page import fetch_doc_page_tool
from tools.memory_tools import save_memory_tool, recall_memory_tool
from tools.highlight_element import highlight_element_tool
from tools.visual_locate import visual_locate_tool
from tools.screenshot_annotate import screenshot_annotate_tool
from tools.classify_page import classify_page_tool
from tools.learn_flow import learn_flow_tool

__all__ = ["get_all_tools", "get_tool_schemas", "get_langchain_tools"]


# ---------------------------------------------------------------------------
# 原始工具实例（用于直接调用）
# ---------------------------------------------------------------------------
_ALL_TOOLS = [
    search_docs_tool,
    fetch_doc_page_tool,
    save_memory_tool,
    recall_memory_tool,
    highlight_element_tool,
    visual_locate_tool,
    screenshot_annotate_tool,
    classify_page_tool,
    learn_flow_tool,
]


# ---------------------------------------------------------------------------
# LangChain StructuredTool 包装
# ---------------------------------------------------------------------------
def _make_langchain_tool(tool_instance) -> StructuredTool:
    """
    将自定义工具包装为 LangChain StructuredTool。

    从 tool.schema 中提取参数定义，映射到 LangChain 的 args_schema。
    """
    import pydantic
    from typing import Any

    # 从 schema 构建 Pydantic model
    properties = tool_instance.schema.get("parameters", {}).get("properties", {})
    required_fields = set(tool_instance.schema.get("parameters", {}).get("required", []))

    # 动态创建 Pydantic model
    field_defs = {}
    for param_name, param_def in properties.items():
        param_type = param_def.get("type", "string")
        py_type = str  # 默认 string
        if param_type == "integer":
            py_type = int
        elif param_type == "boolean":
            py_type = bool
        elif param_type == "number":
            py_type = float

        default = ... if param_name in required_fields else param_def.get("default")
        description = param_def.get("description", "")

        if default is ...:
            field_defs[param_name] = (py_type, pydantic.Field(description=description))
        else:
            field_defs[param_name] = (py_type, pydantic.Field(default=default, description=description))

    # 创建 Pydantic model
    args_model = pydantic.create_model(f"{tool_instance.name}Args", **field_defs)

    # 创建 execute 函数（LangChain 调用时传入 kwargs）
    async def execute_fn(**kwargs) -> str:
        return await tool_instance.execute(**kwargs)

    execute_fn.__name__ = tool_instance.name
    execute_fn.__doc__ = tool_instance.description

    return StructuredTool(
        name=tool_instance.name,
        description=tool_instance.description,
        args_schema=args_model,
        coroutine=execute_fn,
    )


# 缓存 LangChain 工具列表
_langchain_tools: list[StructuredTool] | None = None


def get_langchain_tools() -> list[StructuredTool]:
    """返回 LangChain StructuredTool 列表（供 ToolNode 使用）。"""
    global _langchain_tools
    if _langchain_tools is None:
        _langchain_tools = [_make_langchain_tool(t) for t in _ALL_TOOLS]
    return _langchain_tools


def get_all_tools() -> list:
    """返回原始工具实例列表。"""
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 Function Calling schema。"""
    return [tool.schema for tool in _ALL_TOOLS]
