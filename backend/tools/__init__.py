"""
求问 — 工具集注册表
===================

工具清单：
  Phase 1: search_docs, fetch_doc_page, save_memory, recall_memory
  Phase 2: highlight_element, visual_locate, screenshot_annotate
  Phase 3: classify_page, learn_flow

关键设计（懒加载）：
  - _TOOL_REGISTRY: 工具名 → "模块路径:属性名" 映射表
  - _load_tool(name): 按需加载单个工具，结果缓存
  - get_all_tools(): 返回所有工具实例（按需加载 + 缓存）
  - get_langchain_tools(deps): 返回 LangChain StructuredTool，通过 partial 注入依赖
  - 依赖注入：long_term_memory / fingerprint_storage 在 agent.initialize() 后传入

灵感来源：Scrapling 的 __getattr__ 懒加载模式。
"""

import functools
import importlib
from typing import Any

from langchain_core.tools import StructuredTool
import pydantic

__all__ = ["get_all_tools", "get_tool_schemas", "get_langchain_tools", "get_tool_by_name"]


# ---------------------------------------------------------------------------
# 懒加载注册表：工具名 → "模块路径:属性名"
# ---------------------------------------------------------------------------
_TOOL_REGISTRY = {
    "search_docs": "tools.search_docs:search_docs_tool",
    "fetch_doc_page": "tools.fetch_doc_page:fetch_doc_page_tool",
    "save_memory": "tools.memory_tools:save_memory_tool",
    "recall_memory": "tools.memory_tools:recall_memory_tool",
    "highlight_element": "tools.highlight_element:highlight_element_tool",
    "visual_locate": "tools.visual_locate:visual_locate_tool",
    "screenshot_annotate": "tools.screenshot_annotate:screenshot_annotate_tool",
    "classify_page": "tools.classify_page:classify_page_tool",
    "learn_flow": "tools.learn_flow:learn_flow_tool",
    "browser_snapshot": "tools.browser_tools:browser_snapshot_tool",
    "browser_interact": "tools.browser_tools:browser_interact_tool",
    "browser_find": "tools.browser_tools:browser_find_tool",
}

# 缓存已加载的工具实例
_loaded_tools: dict[str, object] = {}


def _load_tool(name: str):
    """按需加载单个工具（首次加载后缓存）。"""
    if name in _loaded_tools:
        return _loaded_tools[name]

    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        raise KeyError(f"未知工具: {name}，可用: {list(_TOOL_REGISTRY.keys())}")

    module_path, attr = entry.split(":")
    module = importlib.import_module(module_path)
    tool = getattr(module, attr)
    _loaded_tools[name] = tool
    return tool


def get_tool_by_name(name: str):
    """按名称获取单个工具实例。"""
    return _load_tool(name)


# ---------------------------------------------------------------------------
# 原始工具实例（懒加载）
# ---------------------------------------------------------------------------
def get_all_tools() -> list:
    """返回所有工具实例（按需加载 + 缓存）。"""
    return [_load_tool(name) for name in _TOOL_REGISTRY]


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


def get_langchain_tools(
    long_term_memory=None,
    vision_model=None,
    llm=None,
    fingerprint_storage=None,
    browser_controller=None,
) -> list[StructuredTool]:
    """
    返回 LangChain StructuredTool 列表（支持依赖注入）。

    Args:
        long_term_memory: Chroma 向量库实例
        vision_model: moondream 视觉模型
        llm: LLM 实例
        fingerprint_storage: 元素指纹存储
        browser_controller: 浏览器控制器

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
    if fingerprint_storage:
        deps["fingerprint_storage"] = fingerprint_storage
    if browser_controller:
        deps["browser_controller"] = browser_controller

    tools = get_all_tools()  # 懒加载
    _langchain_tools = [_make_langchain_tool(t, **deps) for t in tools]
    return _langchain_tools


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 Function Calling schema。"""
    return [tool.schema for tool in get_all_tools()]
