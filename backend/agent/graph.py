"""
求问 — 多 Agent 协作图
=====================

Supervisor + Workers 架构：
  用户提问 → Supervisor 拆解 → 并行 Workers → 聚合 → LLM 回复
                                    ↓ (失败)
                               fallback 单 Agent

性能目标：复合指令（≥2 子任务）总耗时 < 原架构 * 0.65
"""

import asyncio
import json
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.state import AgentState
from agent.supervisor import Supervisor
from agent.workers import RAGWorker, VisionWorker, FlowWorker, HighlightWorker
from utils.tracing import trace_span

logger = structlog.get_logger()

# Worker 并发上限（避免资源争抢）
MAX_CONCURRENT_WORKERS = 3

# Worker 类型映射
WORKER_TYPES = {"rag", "vision", "flow", "highlight"}


async def supervisor_node(state: AgentState, supervisor: Supervisor) -> dict:
    """
    Supervisor 节点：拆解用户问题为任务计划。

    输入：user_query + 最近对话历史
    输出：task_plan (dict)
    """
    query = state.get("user_query", "")
    history = [m.content for m in state.get("messages", []) if hasattr(m, "content")][-6:]

    async with trace_span("supervisor.plan", query=query[:50]) as span:
        plan = await supervisor.plan(query, history)
        span.set_attribute("steps", len(plan.get("steps", [])))
        span.set_attribute("use_fallback", plan.get("use_fallback", False))

    return {"task_plan": plan}


async def worker_dispatch_node(state: AgentState, workers: dict) -> dict:
    """
    Worker 分发节点：并行执行 Supervisor 拆解的子任务。

    使用 asyncio.gather 并行执行所有 pending 步骤。
    """
    plan = state.get("task_plan") or {}
    steps = plan.get("steps", [])
    use_fallback = plan.get("use_fallback", True)

    if use_fallback or not steps:
        return {"use_fallback": True, "worker_results": {}}

    # 过滤出待执行的步骤
    pending_steps = [s for s in steps if s.get("status") == "pending"]
    if not pending_steps:
        return {"worker_results": {}}

    async with trace_span("workers.execute", count=len(pending_steps)) as span:
        # 并行执行（限制并发数）
        results = await _execute_workers_parallel(pending_steps, workers)
        span.set_attribute("success_count", sum(1 for r in results.values() if r.get("success")))

    return {"worker_results": results}


async def _execute_workers_parallel(steps: list, workers: dict) -> dict:
    """并行执行多个 Worker，限制并发数。"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)
    results = {}

    async def run_step(index: int, step: dict):
        async with semaphore:
            step_type = step.get("type", "")
            params = step.get("params", {})
            worker = workers.get(step_type)

            if not worker:
                results[index] = {"success": False, "error": f"未知任务类型: {step_type}"}
                return

            try:
                if step_type == "rag":
                    result = await worker.execute(params.get("query", ""))
                elif step_type == "vision":
                    result = await worker.execute(params.get("target", ""))
                elif step_type == "flow":
                    result = await worker.execute(params.get("intent", ""))
                elif step_type == "highlight":
                    result = await worker.execute(
                        selector=params.get("selector", "auto"),
                        description=params.get("description", ""),
                        page_url=params.get("page_url", ""),
                    )
                else:
                    result = {"success": False, "error": f"未实现: {step_type}"}

                results[index] = result
            except Exception as e:
                results[index] = {"success": False, "error": str(e)}

    # 并行执行所有步骤
    tasks = [run_step(i, step) for i, step in enumerate(steps)]
    await asyncio.gather(*tasks)

    return results


async def aggregate_node(state: AgentState) -> dict:
    """
    聚合节点：汇总 Worker 结果，构建上下文供 LLM 生成回复。

    将 Worker 结果格式化为上下文文本，注入到消息中。
    """
    worker_results = state.get("worker_results", {})
    if not worker_results:
        return {}

    # 汇总结果
    context_parts = []
    highlights = []

    for index, result in sorted(worker_results.items()):
        if not result.get("success"):
            context_parts.append(f"[任务 {index+1}] 失败: {result.get('error', '未知错误')}")
            continue

        if "results" in result:
            # RAG 结果
            docs = result["results"]
            doc_texts = [d.get("text", "")[:200] for d in docs[:3]]
            context_parts.append(f"[文档检索] {' | '.join(doc_texts)}")

        if "location" in result:
            # 视觉定位结果
            loc = result["location"]
            context_parts.append(f"[视觉定位] x={loc.get('x')}, y={loc.get('y')}, 置信度={loc.get('confidence')}")

        if "flow" in result:
            # 操作流结果
            flow = result["flow"]
            steps = flow.get("steps", [])
            context_parts.append(f"[操作流] {len(steps)} 个步骤")

        if "highlight" in result:
            # 高亮结果
            highlights.append(result["highlight"])

    # 构建聚合上下文
    if context_parts:
        aggregated = "并行任务结果：\n" + "\n".join(context_parts)
        # 注入到消息中（作为 system message）
        return {
            "messages": [SystemMessage(content=aggregated)],
            "worker_highlights": highlights,
        }

    return {"worker_highlights": highlights}


async def fallback_node(state: AgentState, fallback_fn) -> dict:
    """
    降级节点：调用原单 Agent 处理。

    当 Supervisor 解析失败或超时时触发。
    """
    query = state.get("user_query", "")
    logger.info("降级到单 Agent", query=query[:50])

    # 调用原 Agent 的 stream_reply 逻辑
    # 这里简化为直接返回标记，由上层处理
    return {"use_fallback": True}


def build_multi_agent_graph(
    supervisor: Supervisor,
    workers: dict,
    fallback_fn=None,
):
    """
    构建多 Agent 协作图。

    流程：
      1. supervisor_node → 拆解任务
      2. worker_dispatch_node → 并行执行
      3. aggregate_node → 汇总结果
      4. 如果 use_fallback → fallback_node

    Args:
        supervisor: Supervisor 实例
        workers: {"rag": RAGWorker, "vision": VisionWorker, ...}
        fallback_fn: 降级函数（原单 Agent 的处理逻辑）
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("supervisor", lambda state: supervisor_node(state, supervisor))
    graph.add_node("workers", lambda state: worker_dispatch_node(state, workers))
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("fallback", lambda state: fallback_node(state, fallback_fn))

    # 边：supervisor → 检查是否降级
    def after_supervisor(state: AgentState) -> str:
        plan = state.get("task_plan") or {}
        if plan.get("use_fallback", True):
            return "fallback"
        return "workers"

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", after_supervisor, {
        "workers": "workers",
        "fallback": "fallback",
    })

    # workers → aggregate
    graph.add_edge("workers", "aggregate")
    graph.add_edge("aggregate", END)
    graph.add_edge("fallback", END)

    return graph.compile()
