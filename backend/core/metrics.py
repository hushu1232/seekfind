"""
求问 — Prometheus 指标
=====================

职责：
  1. 定义 Prometheus 指标
  2. 暴露指标端点
  3. 记录请求指标

指标类型：
  - Counter: 计数器（请求数、错误数）
  - Histogram: 直方图（响应时间）
  - Gauge: 仪表盘（活跃连接数）
"""

import time
from functools import wraps
from typing import Optional

import structlog

logger = structlog.get_logger()

# 尝试导入 prometheus_client
try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client 未安装，指标收集不可用")


# ---------------------------------------------------------------------------
# 指标定义
# ---------------------------------------------------------------------------

if PROMETHEUS_AVAILABLE:
    # HTTP 请求指标
    HTTP_REQUESTS_TOTAL = Counter(
        'qiuwen_http_requests_total',
        'Total HTTP requests',
        ['method', 'endpoint', 'status']
    )

    HTTP_REQUEST_DURATION = Histogram(
        'qiuwen_http_request_duration_seconds',
        'HTTP request duration in seconds',
        ['method', 'endpoint'],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )

    # WebSocket 指标
    WS_CONNECTIONS = Gauge(
        'qiuwen_ws_connections',
        'Active WebSocket connections'
    )

    WS_MESSAGES_TOTAL = Counter(
        'qiuwen_ws_messages_total',
        'Total WebSocket messages',
        ['direction', 'type']
    )

    # Agent 指标
    AGENT_QUERIES_TOTAL = Counter(
        'qiuwen_agent_queries_total',
        'Total agent queries',
        ['intent', 'status']
    )

    AGENT_QUERY_DURATION = Histogram(
        'qiuwen_agent_query_duration_seconds',
        'Agent query duration in seconds',
        ['intent'],
        buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0]
    )

    # LLM 指标
    LLM_CALLS_TOTAL = Counter(
        'qiuwen_llm_calls_total',
        'Total LLM calls',
        ['model', 'status']
    )

    LLM_LATENCY = Histogram(
        'qiuwen_llm_latency_seconds',
        'LLM inference latency in seconds',
        ['model'],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
    )

    # 检索指标
    RETRIEVAL_CALLS_TOTAL = Counter(
        'qiuwen_retrieval_calls_total',
        'Total retrieval calls',
        ['status']
    )

    RETRIEVAL_DURATION = Histogram(
        'qiuwen_retrieval_duration_seconds',
        'Retrieval duration in seconds',
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0]
    )

    # 缓存指标
    CACHE_HITS_TOTAL = Counter(
        'qiuwen_cache_hits_total',
        'Total cache hits',
        ['cache_level']
    )

    CACHE_MISSES_TOTAL = Counter(
        'qiuwen_cache_misses_total',
        'Total cache misses',
        ['cache_level']
    )

    # 工具调用指标
    TOOL_CALLS_TOTAL = Counter(
        'qiuwen_tool_calls_total',
        'Total tool calls',
        ['tool', 'status']
    )

    TOOL_DURATION = Histogram(
        'qiuwen_tool_duration_seconds',
        'Tool call duration in seconds',
        ['tool'],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
    )


# ---------------------------------------------------------------------------
# 指标记录函数
# ---------------------------------------------------------------------------

def record_http_request(method: str, endpoint: str, status: int, duration: float):
    """记录 HTTP 请求"""
    if PROMETHEUS_AVAILABLE:
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=str(status)).inc()
        HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


def record_ws_connection(delta: int):
    """记录 WebSocket 连接变化"""
    if PROMETHEUS_AVAILABLE:
        WS_CONNECTIONS.inc(delta)


def record_ws_message(direction: str, msg_type: str):
    """记录 WebSocket 消息"""
    if PROMETHEUS_AVAILABLE:
        WS_MESSAGES_TOTAL.labels(direction=direction, type=msg_type).inc()


def record_agent_query(intent: str, status: str, duration: float):
    """记录 Agent 查询"""
    if PROMETHEUS_AVAILABLE:
        AGENT_QUERIES_TOTAL.labels(intent=intent, status=status).inc()
        AGENT_QUERY_DURATION.labels(intent=intent).observe(duration)


def record_llm_call(model: str, status: str, latency: float):
    """记录 LLM 调用"""
    if PROMETHEUS_AVAILABLE:
        LLM_CALLS_TOTAL.labels(model=model, status=status).inc()
        LLM_LATENCY.labels(model=model).observe(latency)


def record_retrieval(status: str, duration: float):
    """记录检索调用"""
    if PROMETHEUS_AVAILABLE:
        RETRIEVAL_CALLS_TOTAL.labels(status=status).inc()
        RETRIEVAL_DURATION.observe(duration)


def record_cache_hit(level: str):
    """记录缓存命中"""
    if PROMETHEUS_AVAILABLE:
        CACHE_HITS_TOTAL.labels(cache_level=level).inc()


def record_cache_miss(level: str):
    """记录缓存未命中"""
    if PROMETHEUS_AVAILABLE:
        CACHE_MISSES_TOTAL.labels(cache_level=level).inc()


def record_tool_call(tool: str, status: str, duration: float):
    """记录工具调用"""
    if PROMETHEUS_AVAILABLE:
        TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()
        TOOL_DURATION.labels(tool=tool).observe(duration)


# ---------------------------------------------------------------------------
# 指标端点
# ---------------------------------------------------------------------------

def get_metrics_content() -> bytes:
    """获取 Prometheus 指标内容"""
    if PROMETHEUS_AVAILABLE:
        return generate_latest()
    return b"# Prometheus client not available\n"


def get_metrics_content_type() -> str:
    """获取指标内容类型"""
    if PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST
    return "text/plain"


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------

def track_time(metric_func, labels_func=None):
    """
    跟踪函数执行时间

    Args:
        metric_func: 记录指标的函数
        labels_func: 从函数参数生成标签的函数
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start

                labels = labels_func(*args, **kwargs) if labels_func else {}
                metric_func(duration=duration, **labels)

                return result
            except Exception as e:
                duration = time.time() - start
                labels = labels_func(*args, **kwargs) if labels_func else {}
                metric_func(duration=duration, status="error", **labels)
                raise

        return wrapper
    return decorator
