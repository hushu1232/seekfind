"""
求问 — 可观测性模块
==================

职责：
  1. 指标收集（Metrics）
  2. 分布式追踪（Tracing）
  3. 结构化日志（Logging）
  4. 健康检查（Health Check）

指标类型：
  - Counter: 计数器（请求数、错误数）
  - Histogram: 直方图（响应时间、延迟）
  - Gauge: 仪表盘（活跃连接数、队列长度）
"""

import time
import uuid
from typing import Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import defaultdict
from functools import wraps

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 指标收集
# ---------------------------------------------------------------------------

@dataclass
class Metric:
    """指标"""
    name: str
    value: float
    timestamp: float
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    指标收集器

    收集 Counter、Histogram、Gauge 类型的指标。
    """

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1, labels: Optional[dict[str, str]] = None):
        """递增计数器"""
        key = self._make_key(name, labels)
        self._counters[key] += value

    def observe(self, name: str, value: float, labels: Optional[dict[str, str]] = None):
        """记录直方图值"""
        key = self._make_key(name, labels)
        self._histograms[key].append(value)

        # 限制大小，防止内存泄漏
        if len(self._histograms[key]) > 10000:
            self._histograms[key] = self._histograms[key][-5000:]

    def set_gauge(self, name: str, value: float, labels: Optional[dict[str, str]] = None):
        """设置仪表盘值"""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def get_metrics(self) -> list[Metric]:
        """获取所有指标"""
        metrics = []
        timestamp = time.time()

        # Counter
        for key, value in self._counters.items():
            name, labels = self._parse_key(key)
            metrics.append(Metric(name, value, timestamp, labels))

        # Histogram
        for key, values in self._histograms.items():
            name, labels = self._parse_key(key)
            if values:
                metrics.append(Metric(f"{name}_count", len(values), timestamp, labels))
                metrics.append(Metric(f"{name}_sum", sum(values), timestamp, labels))
                metrics.append(Metric(f"{name}_avg", sum(values) / len(values), timestamp, labels))
                metrics.append(Metric(f"{name}_p50", self._percentile(values, 50), timestamp, labels))
                metrics.append(Metric(f"{name}_p95", self._percentile(values, 95), timestamp, labels))
                metrics.append(Metric(f"{name}_p99", self._percentile(values, 99), timestamp, labels))

        # Gauge
        for key, value in self._gauges.items():
            name, labels = self._parse_key(key)
            metrics.append(Metric(name, value, timestamp, labels))

        return metrics

    def reset(self):
        """重置所有指标"""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()

    def _make_key(self, name: str, labels: Optional[dict[str, str]] = None) -> str:
        """生成指标键"""
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name

    def _parse_key(self, key: str) -> tuple[str, dict[str, str]]:
        """解析指标键"""
        if "{" in key:
            name = key.split("{")[0]
            label_str = key.split("{")[1].rstrip("}")
            labels = dict(item.split("=") for item in label_str.split(","))
            return name, labels
        return key, {}

    def _percentile(self, values: list[float], p: int) -> float:
        """计算百分位数"""
        if not values:
            return 0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * p / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]


# ---------------------------------------------------------------------------
# 分布式追踪
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """追踪 Span"""
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    name: str
    start_time: float
    end_time: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok, error


class Tracer:
    """
    分布式追踪器

    记录请求的完整调用链路。
    """

    def __init__(self):
        self._spans: list[Span] = []
        self._current_span: Optional[Span] = None

    @contextmanager
    def start_span(self, name: str, attributes: Optional[dict[str, Any]] = None):
        """
        开始一个新的 Span

        使用方法:
            with tracer.start_span("process_query") as span:
                span.attributes["query"] = query
                # 业务逻辑
        """
        span = Span(
            trace_id=self._get_trace_id(),
            span_id=self._generate_id(),
            parent_id=self._current_span.span_id if self._current_span else None,
            name=name,
            start_time=time.time(),
            attributes=attributes or {},
        )

        parent_span = self._current_span
        self._current_span = span

        try:
            yield span
        except Exception as e:
            span.status = "error"
            span.events.append({
                "name": "exception",
                "timestamp": time.time(),
                "attributes": {
                    "exception.type": type(e).__name__,
                    "exception.message": str(e),
                },
            })
            raise
        finally:
            span.end_time = time.time()
            self._spans.append(span)
            self._current_span = parent_span

    def get_current_span(self) -> Optional[Span]:
        """获取当前 Span"""
        return self._current_span

    def get_spans(self, trace_id: Optional[str] = None) -> list[Span]:
        """获取所有 Span"""
        if trace_id:
            return [s for s in self._spans if s.trace_id == trace_id]
        return self._spans

    def clear(self):
        """清空所有 Span"""
        self._spans.clear()

    def _get_trace_id(self) -> str:
        """获取 Trace ID"""
        if self._current_span:
            return self._current_span.trace_id
        return self._generate_id()

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# 结构化日志
# ---------------------------------------------------------------------------

class RequestLogger:
    """
    请求日志记录器

    记录请求的完整生命周期。
    """

    def __init__(self):
        self._logger = structlog.get_logger("request")

    def log_request(
        self,
        request_id: str,
        method: str,
        path: str,
        **kwargs,
    ):
        """记录请求开始"""
        self._logger.info(
            "request_started",
            request_id=request_id,
            method=method,
            path=path,
            **kwargs,
        )

    def log_response(
        self,
        request_id: str,
        status_code: int,
        duration: float,
        **kwargs,
    ):
        """记录请求完成"""
        self._logger.info(
            "request_completed",
            request_id=request_id,
            status_code=status_code,
            duration_ms=round(duration * 1000, 2),
            **kwargs,
        )

    def log_error(
        self,
        request_id: str,
        error: Exception,
        **kwargs,
    ):
        """记录请求错误"""
        self._logger.error(
            "request_failed",
            request_id=request_id,
            error_type=type(error).__name__,
            error_message=str(error),
            **kwargs,
        )

    def log_tool_call(
        self,
        request_id: str,
        tool_name: str,
        duration: float,
        success: bool,
        **kwargs,
    ):
        """记录工具调用"""
        self._logger.info(
            "tool_call",
            request_id=request_id,
            tool_name=tool_name,
            duration_ms=round(duration * 1000, 2),
            success=success,
            **kwargs,
        )

    def log_llm_call(
        self,
        request_id: str,
        model: str,
        duration: float,
        tokens: int,
        **kwargs,
    ):
        """记录 LLM 调用"""
        self._logger.info(
            "llm_call",
            request_id=request_id,
            model=model,
            duration_ms=round(duration * 1000, 2),
            tokens=tokens,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@dataclass
class HealthCheckResult:
    """健康检查结果"""
    status: str  # healthy, degraded, unhealthy
    checks: dict[str, bool]
    timestamp: float
    details: Optional[dict] = None


class HealthChecker:
    """
    健康检查器

    检查各个组件的健康状态。
    """

    def __init__(self):
        self._checks: dict[str, callable] = {}

    def register_check(self, name: str, check_func: callable):
        """注册健康检查"""
        self._checks[name] = check_func

    async def check(self) -> HealthCheckResult:
        """执行健康检查"""
        checks = {}
        all_healthy = True

        for name, check_func in self._checks.items():
            try:
                result = await check_func()
                checks[name] = result
                if not result:
                    all_healthy = False
            except Exception:
                checks[name] = False
                all_healthy = False

        status = "healthy" if all_healthy else "degraded"

        return HealthCheckResult(
            status=status,
            checks=checks,
            timestamp=time.time(),
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_metrics: Optional[MetricsCollector] = None
_tracer: Optional[Tracer] = None
_request_logger: Optional[RequestLogger] = None
_health_checker: Optional[HealthChecker] = None


def get_metrics() -> MetricsCollector:
    """获取指标收集器单例"""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def get_tracer() -> Tracer:
    """获取追踪器单例"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def get_request_logger() -> RequestLogger:
    """获取请求日志记录器单例"""
    global _request_logger
    if _request_logger is None:
        _request_logger = RequestLogger()
    return _request_logger


def get_health_checker() -> HealthChecker:
    """获取健康检查器单例"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------

def trace_function(name: Optional[str] = None):
    """
    追踪函数执行

    使用方法:
        @trace_function("process_query")
        async def process_query(query: str):
            # 业务逻辑
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            span_name = name or func.__name__

            with tracer.start_span(span_name) as span:
                # 记录函数参数
                span.attributes["args"] = str(args)[:200]
                span.attributes["kwargs"] = str(kwargs)[:200]

                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    span.attributes["duration"] = time.time() - start_time
                    return result
                except Exception as e:
                    span.status = "error"
                    raise

        return wrapper
    return decorator


def record_metrics(name: str):
    """
    记录函数指标

    使用方法:
        @record_metrics("search_docs")
        async def search_docs(query: str):
            # 业务逻辑
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            metrics = get_metrics()
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time

                metrics.increment(f"{name}_total")
                metrics.observe(f"{name}_duration", duration)

                return result
            except Exception as e:
                metrics.increment(f"{name}_errors")
                raise

        return wrapper
    return decorator
