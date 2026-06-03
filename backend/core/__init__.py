"""
求问 — 核心模块
===============

P0 级别改进：架构增强

模块：
  - degradation: 功能降级管理器
  - security: 安全守卫
  - cache: 多级缓存管理器
  - observability: 可观测性（指标、追踪、日志）
"""

from .cache import CacheManager
from .degradation import (
    FeatureDegradationManager,
    FeatureStatus,
    get_degradation_manager,
)
from .observability import (
    MetricsCollector,
    RequestLogger,
    Tracer,
    get_metrics,
    get_request_logger,
    get_tracer,
)
from .security import (
    SecurityCheckResult,
    SecurityGuard,
    get_security_guard,
)

__all__ = [
    # degradation
    "FeatureDegradationManager",
    "FeatureStatus",
    "get_degradation_manager",
    # security
    "SecurityGuard",
    "SecurityCheckResult",
    "get_security_guard",
    # cache
    "CacheManager",
    # observability
    "MetricsCollector",
    "Tracer",
    "RequestLogger",
    "get_metrics",
    "get_tracer",
    "get_request_logger",
]
