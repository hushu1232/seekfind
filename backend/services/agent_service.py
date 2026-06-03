"""
求问 — Agent 推理服务
====================

职责：
  1. 管理 Agent 生命周期
  2. 处理用户查询
  3. 流式返回结果
  4. 集成安全检查和可观测性
"""

from collections.abc import AsyncGenerator

import structlog
from core.degradation import get_degradation_manager
from core.observability import get_metrics, get_request_logger, get_tracer
from core.security import get_security_guard

from .base import BaseService

logger = structlog.get_logger()


class AgentService(BaseService):
    """
    Agent 推理服务

    封装 QiuWenAgent，提供统一的服务接口。
    """

    def __init__(self):
        super().__init__("agent")
        self._agent = None
        self._security = get_security_guard()
        self._metrics = get_metrics()
        self._tracer = get_tracer()
        self._request_logger = get_request_logger()
        self._degradation = get_degradation_manager()

    async def initialize(self) -> None:
        """初始化 Agent"""
        from agent_engine import QiuWenAgent

        self._agent = QiuWenAgent()
        await self._agent.initialize()

        # 注册降级管理
        self._degradation.register_feature({
            "name": "agent",
            "display_name": "Agent 引擎",
            "auto_retry": True,
            "retry_interval": 30.0,
            "max_retries": 3,
            "recovery_func": self._reinitialize,
        })

        logger.info("Agent 服务初始化完成")

    async def shutdown(self) -> None:
        """关闭 Agent"""
        if self._agent:
            await self._agent.shutdown()
            self._agent = None

        logger.info("Agent 服务已关闭")

    async def health_check(self) -> bool:
        """健康检查"""
        return self._agent is not None

    async def process_query(
        self,
        query: str,
        session_id: str,
        page_context: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        处理用户查询，流式返回结果

        Args:
            query: 用户查询
            session_id: 会话 ID
            page_context: 页面上下文

        Yields:
            dict: 响应消息
        """
        request_id = f"{session_id}:{id(query)}"
        metrics = self._metrics
        tracer = self._tracer

        # 安全检查
        check_result = self._security.validate_input(query)
        if not check_result.is_safe:
            yield {
                "type": "error",
                "message": check_result.reason,
            }
            return

        # 记录请求
        self._request_logger.log_request(
            request_id=request_id,
            method="process_query",
            path="agent_service",
            query=query[:100],
        )

        # 增加查询计数
        metrics.increment("agent.queries.total")

        with tracer.start_span("agent.process_query") as span:
            span.attributes["query"] = query[:100]
            span.attributes["session_id"] = session_id

            start_time = __import__('time').time()

            try:
                # 获取会话
                session = await self._get_session(session_id)
                if not session:
                    yield {
                        "type": "error",
                        "message": "会话不存在",
                    }
                    return

                # 处理查询
                async for chunk in self._agent.stream_reply(query, session, page_context):
                    # 净化输出
                    if chunk.get("type") == "agent_response":
                        chunk["text"] = self._security.sanitize_output(chunk["text"])

                    yield chunk

                # 记录成功
                duration = __import__('time').time() - start_time
                metrics.observe("agent.query.duration", duration)
                metrics.increment("agent.queries.success")

                self._request_logger.log_response(
                    request_id=request_id,
                    status_code=200,
                    duration=duration,
                )

            except Exception as e:
                # 记录失败
                duration = __import__('time').time() - start_time
                metrics.increment("agent.queries.error")
                metrics.observe("agent.query.duration", duration)

                self._request_logger.log_error(
                    request_id=request_id,
                    error=e,
                )

                # 降级处理
                self._degradation.degrade("agent", str(e))

                yield {
                    "type": "error",
                    "message": "处理查询时出错，请稍后重试",
                }

    async def _get_session(self, session_id: str):
        """获取或创建会话"""
        # 从 app.py 的 active_sessions 获取
        from app import active_sessions
        return active_sessions.get(session_id)

    async def _reinitialize(self) -> bool:
        """重新初始化 Agent"""
        try:
            if self._agent:
                await self._agent.shutdown()

            from agent_engine import QiuWenAgent
            self._agent = QiuWenAgent()
            await self._agent.initialize()

            return True
        except Exception as e:
            logger.error("Agent 重新初始化失败", error=str(e))
            return False

    def get_agent(self):
        """获取 Agent 实例"""
        return self._agent
