"""
求问 — 服务基类
===============

所有服务的基类，定义统一的生命周期和健康检查接口。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ServiceStatus(StrEnum):
    """服务状态"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class BaseService(ABC):
    """
    服务基类

    所有服务必须实现以下方法：
      - initialize: 初始化服务
      - shutdown: 关闭服务
      - health_check: 健康检查
    """

    def __init__(self, name: str):
        self._name = name
        self._status = ServiceStatus.STOPPED
        self._started_at: datetime | None = None
        self._error: str | None = None

    @property
    def name(self) -> str:
        """服务名称"""
        return self._name

    @property
    def status(self) -> ServiceStatus:
        """服务状态"""
        return self._status

    @property
    def is_running(self) -> bool:
        """是否运行中"""
        return self._status == ServiceStatus.RUNNING

    @property
    def uptime(self) -> float | None:
        """运行时间（秒）"""
        if self._started_at and self._status == ServiceStatus.RUNNING:
            return (datetime.now() - self._started_at).total_seconds()
        return None

    async def start(self):
        """启动服务"""
        logger.info("服务启动中", service=self._name)
        self._status = ServiceStatus.INITIALIZING

        try:
            await self.initialize()
            self._status = ServiceStatus.RUNNING
            self._started_at = datetime.now()
            self._error = None
            logger.info("服务已启动", service=self._name)
        except Exception as e:
            self._status = ServiceStatus.ERROR
            self._error = str(e)
            logger.error("服务启动失败", service=self._name, error=str(e))
            raise

    async def stop(self):
        """停止服务"""
        logger.info("服务停止中", service=self._name)
        self._status = ServiceStatus.STOPPING

        try:
            await self.shutdown()
            self._status = ServiceStatus.STOPPED
            self._started_at = None
            logger.info("服务已停止", service=self._name)
        except Exception as e:
            self._status = ServiceStatus.ERROR
            self._error = str(e)
            logger.error("服务停止失败", service=self._name, error=str(e))
            raise

    @abstractmethod
    async def initialize(self) -> None:
        """
        初始化服务

        子类必须实现此方法，用于初始化服务所需的资源。
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        关闭服务

        子类必须实现此方法，用于释放服务占用的资源。
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查

        子类必须实现此方法，用于检查服务是否健康。

        Returns:
            bool: 服务是否健康
        """
        pass

    def get_info(self) -> dict[str, Any]:
        """获取服务信息"""
        return {
            "name": self._name,
            "status": self._status.value,
            "uptime": self.uptime,
            "error": self._error,
        }
