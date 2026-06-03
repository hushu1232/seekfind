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

from .degradation import (
    FeatureDegradationManager,
    FeatureStatus,
    get_degradation_manager,
)
from .security import (
    SecurityGuard,
    SecurityCheckResult,
    get_security_guard,
)
from .cache import CacheManager
from .observability import (
    MetricsCollector,
    Tracer,
    RequestLogger,
    get_metrics,
    get_tracer,
    get_request_logger,
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
