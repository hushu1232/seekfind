"""
求问 — 日志配置
===============

职责：
  1. 配置结构化日志
  2. 日志轮转
  3. 日志级别管理
  4. 请求链路追踪

日志格式：
  JSON 结构化日志，便于 ELK 收集和分析
"""

import logging
import sys
from pathlib import Path

import structlog


def setup_logging(
    log_level: str = "INFO",
    log_file: str | None = None,
    json_format: bool = True,
):
    """
    配置日志系统

    Args:
        log_level: 日志级别
        log_file: 日志文件路径（可选）
        json_format: 是否使用 JSON 格式
    """
    # 配置 structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准库日志
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        # 日志轮转
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        handlers.append(file_handler)

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
        handlers=handlers,
    )

    # 设置第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)


class RequestContextFilter(logging.Filter):
    """请求上下文日志过滤器"""

    def filter(self, record):
        # 添加请求 ID
        import contextvars
        request_id = contextvars.copy_context().get("request_id", None)
        if request_id:
            record.request_id = request_id
        return True


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        structlog.BoundLogger: 日志记录器
    """
    return structlog.get_logger(name)
