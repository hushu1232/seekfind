"""
求问 — 可观测性 Tracing
======================

基于 structlog 的轻量级 span 追踪。

功能：
  - 追踪 Agent 执行流程（意图分类 → 工具调用 → 回复）
  - 记录每个步骤的耗时
  - 输出结构化日志（JSON 格式）

用法：
  from utils.tracing import traced, trace_span

  @traced("agent.run_graph")
  async def run_graph(self, ...):
      ...

  # 或手动
  async with trace_span("tool.call", tool_name="search_docs") as span:
      result = await tool.execute(...)
      span.set_attribute("result_count", len(result))
"""

import time
from contextlib import asynccontextmanager
from typing import Any

import structlog

logger = structlog.get_logger()


class Span:
    """
    追踪 span。

    记录开始/结束时间、属性、事件。
    """

    def __init__(self, name: str, **attributes):
        self.name = name
        self.attributes = dict(attributes)
        self.start_time = time.time()
        self.end_time: float | None = None
        self.events: list[dict] = []

    def set_attribute(self, key: str, value: Any) -> None:
        """设置属性。"""
        self.attributes[key] = value

    def add_event(self, name: str, **attributes) -> None:
        """添加事件。"""
        self.events.append({
            "name": name,
            "time": time.time(),
            **attributes,
        })

    def finish(self) -> None:
        """结束 span。"""
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """耗时（毫秒）。"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> dict:
        """转为字典（用于日志输出）。"""
        return {
            "span": self.name,
            "duration_ms": round(self.duration_ms, 1),
            **self.attributes,
            **({"events": self.events} if self.events else {}),
        }


@asynccontextmanager
async def trace_span(name: str, **attributes):
    """
    异步 span 追踪上下文管理器。

    用法：
        async with trace_span("tool.call", tool_name="search_docs") as span:
            result = await tool.execute(...)
            span.set_attribute("result_count", len(result))
    """
    span = Span(name, **attributes)
    try:
        yield span
    except Exception as e:
        span.add_event("error", message=str(e))
        raise
    finally:
        span.finish()
        logger.info("span", **span.to_dict())


def traced(name: str):
    """
    函数追踪装饰器。

    用法：
        @traced("agent.classify_intent")
        async def classify_intent(self, question: str) -> str:
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            async with trace_span(name) as span:
                result = await func(*args, **kwargs)
                if isinstance(result, str):
                    span.set_attribute("result_preview", result[:100])
                return result
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
