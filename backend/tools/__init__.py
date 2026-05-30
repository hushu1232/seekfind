"""
求问 — 工具集注册表
===================

工具清单：
  Phase 1: search_docs, fetch_doc_page, save_memory, recall_memory
  Phase 2: highlight_element, visual_locate, screenshot_annotate
  Phase 3: classify_page, learn_flow

关键设计：
  - get_all_tools(): 返回原始工具实例
  - get_langchain_tools(deps): 返回 LangChain StructuredTool，通过 partial 注入依赖
  - 依赖注入：long_term_memory 在 agent.initialize() 后传入
"""

import functools
from typing import Any

from langchain_core.tools import StructuredTool
import pydantic

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
# 原始工具实例
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
# LangChain StructuredTool 包装（支持依赖注入）
# ---------------------------------------------------------------------------
def _make_langchain_tool(tool_instance, **deps) -> StructuredTool:
    """
    将自定义工具包装为 LangChain StructuredTool。

    通过 functools.partial 将依赖（如 long_term_memory）注入到 execute 方法。
    ToolNode 调用时只传 LLM 提供的 kwargs，依赖已预绑定。
    """
    properties = tool_instance.schema.get("parameters", {}).get("properties", {})
    required_fields = set(tool_instance.schema.get("parameters", {}).get("required", []))

    field_defs = {}
    for param_name, param_def in properties.items():
        param_type = param_def.get("type", "string")
        py_type = str
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

    args_model = pydantic.create_model(f"{tool_instance.name}Args", **field_defs)

    # 用 partial 注入依赖，LLM 只需提供 kwargs
    execute_with_deps = functools.partial(tool_instance.execute, **deps)

    async def execute_fn(**kwargs) -> str:
        return await execute_with_deps(**kwargs)

    execute_fn.__name__ = tool_instance.name
    execute_fn.__doc__ = tool_instance.description

    return StructuredTool(
        name=tool_instance.name,
        description=tool_instance.description,
        args_schema=args_model,
        coroutine=execute_fn,
    )


# 缓存
_langchain_tools: list[StructuredTool] | None = None


def get_langchain_tools(long_term_memory=None, vision_model=None, llm=None) -> list[StructuredTool]:
    """
    返回 LangChain StructuredTool 列表（支持依赖注入）。

    Args:
        long_term_memory: Chroma 向量库实例（注入到 search_docs/save_memory/recall_memory）
        vision_model: moondream 视觉模型（注入到 visual_locate）
        llm: LLM 实例（注入到 classify_page）

    使用 functools.partial 将依赖预绑定到工具的 execute 方法，
    ToolNode 调用时只需传入 LLM 提供的参数。
    """
    global _langchain_tools
    # 依赖变化时重建
    deps = {}
    if long_term_memory:
        deps["long_term_memory"] = long_term_memory
    if vision_model:
        deps["vision_model"] = vision_model
    if llm:
        deps["llm"] = llm

    _langchain_tools = [_make_langchain_tool(t, **deps) for t in _ALL_TOOLS]
    return _langchain_tools


def get_all_tools() -> list:
    """返回原始工具实例列表。"""
    return list(_ALL_TOOLS)


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 Function Calling schema。"""
    return [tool.schema for tool in _ALL_TOOLS]
