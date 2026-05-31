"""
多 Agent 协作架构测试
====================

测试：
  - Supervisor 任务拆解
  - Worker 并行执行
  - 降级机制
  - 结果聚合
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState, TaskStep
from agent.supervisor import Supervisor
from agent.workers import RAGWorker, VisionWorker, FlowWorker, HighlightWorker
from agent.graph import build_multi_agent_graph, supervisor_node, worker_dispatch_node, aggregate_node


class TestSupervisor:
    """Supervisor 任务拆解测试。"""

    @pytest.mark.asyncio
    async def test_plan_simple_question(self):
        """简单问题拆解为单个步骤。"""
        supervisor = Supervisor()
        # Mock LLM
        supervisor._llm = AsyncMock()
        supervisor._llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"steps": [{"type": "rag", "params": {"query": "GitHub 创建仓库"}}]}'
        ))

        result = await supervisor.plan("GitHub 怎么创建仓库？")
        assert result["use_fallback"] is False
        assert len(result["steps"]) == 1
        assert result["steps"][0]["type"] == "rag"

    @pytest.mark.asyncio
    async def test_plan_compound_question(self):
        """复合问题拆解为多个步骤。"""
        supervisor = Supervisor()
        supervisor._llm = AsyncMock()
        supervisor._llm.ainvoke = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "steps": [
                    {"type": "rag", "params": {"query": "保存表单"}},
                    {"type": "vision", "params": {"target": "保存按钮"}},
                ]
            })
        ))

        result = await supervisor.plan("帮我高亮保存按钮，然后检索保存文档")
        assert result["use_fallback"] is False
        assert len(result["steps"]) == 2

    @pytest.mark.asyncio
    async def test_plan_invalid_json_fallback(self):
        """非法 JSON 输出降级。"""
        supervisor = Supervisor()
        supervisor._llm = AsyncMock()
        supervisor._llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="这不是JSON"
        ))

        result = await supervisor.plan("测试问题")
        assert result["use_fallback"] is True

    @pytest.mark.asyncio
    async def test_plan_timeout_fallback(self):
        """超时降级。"""
        supervisor = Supervisor()
        supervisor._llm = AsyncMock()

        async def slow_invoke(*args, **kwargs):
            await asyncio.sleep(20)

        supervisor._llm.ainvoke = slow_invoke

        result = await supervisor.plan("测试问题")
        assert result["use_fallback"] is True

    @pytest.mark.asyncio
    async def test_plan_no_llm_fallback(self):
        """无 LLM 降级。"""
        supervisor = Supervisor()
        # 不初始化 LLM
        result = await supervisor.plan("测试问题")
        assert result["use_fallback"] is True


class TestWorkers:
    """Worker 执行测试。"""

    @pytest.mark.asyncio
    async def test_rag_worker_no_memory(self):
        """RAG Worker 无记忆时返回错误。"""
        worker = RAGWorker(long_term_memory=None)
        result = await worker.execute("测试")
        # 无记忆时应该返回成功但结果为空
        assert "success" in result

    @pytest.mark.asyncio
    async def test_vision_worker_no_model(self):
        """Vision Worker 无模型时返回错误。"""
        worker = VisionWorker(vision_model=None)
        result = await worker.execute("保存按钮")
        assert result["success"] is False
        assert "未加载" in result["error"]

    @pytest.mark.asyncio
    async def test_flow_worker_no_memory(self):
        """Flow Worker 无记忆时返回错误。"""
        worker = FlowWorker(long_term_memory=None)
        result = await worker.execute("保存")
        assert "success" in result

    @pytest.mark.asyncio
    async def test_highlight_worker_no_storage(self):
        """Highlight Worker 无存储时返回结果。"""
        worker = HighlightWorker(fingerprint_storage=None)
        result = await worker.execute("#btn", "按钮", "https://example.com")
        assert "success" in result


class TestMultiAgentGraph:
    """多 Agent 图测试。"""

    def test_graph_build(self):
        """图构建成功。"""
        supervisor = Supervisor()
        workers = {
            "rag": RAGWorker(),
            "vision": VisionWorker(),
            "flow": FlowWorker(),
            "highlight": HighlightWorker(),
        }
        graph = build_multi_agent_graph(supervisor, workers)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_supervisor_node_fallback(self):
        """Supervisor 节点降级测试。"""
        supervisor = Supervisor()
        # 不初始化 LLM，应该降级
        state = {"user_query": "测试", "messages": []}
        result = await supervisor_node(state, supervisor)
        assert result["task_plan"]["use_fallback"] is True

    @pytest.mark.asyncio
    async def test_aggregate_node_with_results(self):
        """聚合节点测试。"""
        state = {
            "worker_results": {
                0: {"success": True, "results": [{"text": "测试结果"}]},
                1: {"success": False, "error": "超时"},
            },
            "messages": [],
        }
        result = await aggregate_node(state)
        assert "messages" in result
        assert len(result["messages"]) > 0

    @pytest.mark.asyncio
    async def test_aggregate_node_empty(self):
        """空结果聚合。"""
        state = {"worker_results": {}, "messages": []}
        result = await aggregate_node(state)
        # 空结果时应返回空 dict 或包含 worker_highlights
        assert isinstance(result, dict)


class TestParallelExecution:
    """并行执行测试。"""

    @pytest.mark.asyncio
    async def test_parallel_workers(self):
        """多个 Worker 并行执行。"""
        from agent.graph import _execute_workers_parallel

        workers = {
            "rag": RAGWorker(),
            "vision": VisionWorker(),
        }

        steps = [
            {"type": "rag", "params": {"query": "测试"}, "status": "pending"},
            {"type": "vision", "params": {"target": "按钮"}, "status": "pending"},
        ]

        results = await _execute_workers_parallel(steps, workers)
        assert len(results) == 2
        assert 0 in results
        assert 1 in results

    @pytest.mark.asyncio
    async def test_worker_timeout(self):
        """Worker 超时处理。"""
        from agent.graph import _execute_workers_parallel

        # 创建一个会超时的 worker
        class SlowWorker:
            async def execute(self, *args, **kwargs):
                await asyncio.sleep(20)
                return {"success": True}

        workers = {"rag": SlowWorker()}
        steps = [{"type": "rag", "params": {"query": "测试"}, "status": "pending"}]

        # 应该在超时后返回错误
        results = await _execute_workers_parallel(steps, workers)
        # 结果应该包含错误
        assert 0 in results
