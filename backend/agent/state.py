"""
求问 — Agent 状态定义
====================

扩展 AgentState，支持 Supervisor + Workers 架构。
"""

from collections.abc import Sequence
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class TaskStep(TypedDict, total=False):
    """Supervisor 拆解的单个子任务。"""
    type: str          # rag / vision / flow / highlight
    params: dict       # 任务参数
    status: str        # pending / running / done / error
    result: Any        # 执行结果


class AgentState(TypedDict, total=False):
    """扩展的 Agent 状态。"""
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Supervisor + Workers 架构
    task_plan: dict | None           # Supervisor 输出的任务计划
    worker_results: dict             # Worker 执行结果 {step_index: result}
    use_fallback: bool               # 是否降级到原单 Agent

    # 上下文
    user_query: str                  # 用户原始问题
    page_context: dict               # 页面上下文
    intent: str                      # 意图分类结果
