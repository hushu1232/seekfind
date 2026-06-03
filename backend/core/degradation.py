"""
求问 — 功能降级管理器
====================

职责：
  1. 管理可选功能的可用状态
  2. 功能降级时通知用户
  3. 自动重试恢复功能
  4. 记录降级事件用于分析

使用场景：
  - 视觉模型不可用时降级
  - Reranker 不可用时降级
  - 企业 API 不可用时降级
  - TTS/ASR 不可用时降级
"""

import asyncio
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

import structlog

logger = structlog.get_logger()


class FeatureStatus(str, Enum):
    """功能状态"""
    AVAILABLE = "available"       # 可用
    DEGRADED = "degraded"         # 降级（部分功能受限）
    UNAVAILABLE = "unavailable"   # 不可用
    RECOVERING = "recovering"     # 恢复中


@dataclass
class DegradationEvent:
    """降级事件"""
    feature: str
    status: FeatureStatus
    reason: str
    timestamp: float
    retry_count: int = 0
    recovered_at: Optional[float] = None


@dataclass
class FeatureConfig:
    """功能配置"""
    name: str
    display_name: str
    auto_retry: bool = True
    retry_interval: float = 60.0  # 重试间隔（秒）
    max_retries: int = 5          # 最大重试次数
    recovery_func: Optional[Callable] = None


class FeatureDegradationManager:
    """
    功能降级管理器

    管理可选功能的可用状态，支持自动重试和恢复。
    """

    def __init__(self, ws_manager=None):
        self._features: dict[str, FeatureStatus] = {}
        self._configs: dict[str, FeatureConfig] = {}
        self._events: list[DegradationEvent] = []
        self._ws_manager = ws_manager
        self._retry_tasks: dict[str, asyncio.Task] = {}
        self._listeners: list[Callable] = []

    def register_feature(self, config: FeatureConfig):
        """注册功能"""
        self._configs[config.name] = config
        self._features[config.name] = FeatureStatus.AVAILABLE
        logger.debug("功能已注册", feature=config.name)

    def degrade(self, feature: str, reason: str, auto_retry: bool = True):
        """
        标记功能降级

        Args:
            feature: 功能名称
            reason: 降级原因
            auto_retry: 是否自动重试
        """
        old_status = self._features.get(feature, FeatureStatus.AVAILABLE)
        self._features[feature] = FeatureStatus.DEGRADED

        # 记录事件
        event = DegradationEvent(
            feature=feature,
            status=FeatureStatus.DEGRADED,
            reason=reason,
            timestamp=time.time(),
        )
        self._events.append(event)

        logger.warning(
            "功能降级",
            feature=feature,
            reason=reason,
            old_status=old_status.value,
        )

        # 通知用户
        self._notify_user(feature, reason)

        # 通知监听器
        self._notify_listeners(feature, FeatureStatus.DEGRADED)

        # 自动重试
        config = self._configs.get(feature)
        if auto_retry and config and config.auto_retry:
            self._schedule_retry(feature)

    def is_available(self, feature: str) -> bool:
        """检查功能是否可用"""
        return self._features.get(feature, FeatureStatus.AVAILABLE) == FeatureStatus.AVAILABLE

    def get_status(self, feature: str) -> FeatureStatus:
        """获取功能状态"""
        return self._features.get(feature, FeatureStatus.AVAILABLE)

    def get_all_status(self) -> dict[str, str]:
        """获取所有功能状态"""
        return {k: v.value for k, v in self._features.items()}

    def get_events(self, feature: Optional[str] = None) -> list[DegradationEvent]:
        """获取降级事件"""
        if feature:
            return [e for e in self._events if e.feature == feature]
        return self._events

    def add_listener(self, listener: Callable):
        """添加状态变化监听器"""
        self._listeners.append(listener)

    def set_ws_manager(self, ws_manager):
        """设置 WebSocket 管理器（用于通知用户）"""
        self._ws_manager = ws_manager

    def _notify_user(self, feature: str, reason: str):
        """通知用户"""
        if self._ws_manager:
            try:
                asyncio.create_task(self._ws_manager.broadcast({
                    "type": "feature_degraded",
                    "feature": feature,
                    "reason": reason,
                    "message": f"功能 {feature} 暂时不可用: {reason}",
                }))
            except Exception as e:
                logger.debug("通知用户失败", error=str(e))

    def _notify_listeners(self, feature: str, status: FeatureStatus):
        """通知监听器"""
        for listener in self._listeners:
            try:
                listener(feature, status)
            except Exception as e:
                logger.debug("监听器通知失败", error=str(e))

    def _schedule_retry(self, feature: str):
        """安排自动重试"""
        # 取消之前的重试任务
        if feature in self._retry_tasks:
            self._retry_tasks[feature].cancel()

        config = self._configs.get(feature)
        if not config:
            return

        async def retry():
            retry_count = 0
            while retry_count < config.max_retries:
                await asyncio.sleep(config.retry_interval)

                # 检查是否已经恢复
                if self._features.get(feature) == FeatureStatus.AVAILABLE:
                    return

                retry_count += 1
                logger.info("尝试恢复功能", feature=feature, attempt=retry_count)

                # 尝试恢复
                self._features[feature] = FeatureStatus.RECOVERING

                try:
                    if config.recovery_func:
                        success = await config.recovery_func()
                        if success:
                            self._features[feature] = FeatureStatus.AVAILABLE
                            logger.info("功能已恢复", feature=feature)
                            self._notify_user(feature, "已恢复")
                            self._notify_listeners(feature, FeatureStatus.AVAILABLE)

                            # 记录恢复事件
                            event = DegradationEvent(
                                feature=feature,
                                status=FeatureStatus.AVAILABLE,
                                reason="自动恢复",
                                timestamp=time.time(),
                                retry_count=retry_count,
                                recovered_at=time.time(),
                            )
                            self._events.append(event)
                            return
                except Exception as e:
                    logger.debug("恢复失败", feature=feature, error=str(e))

                self._features[feature] = FeatureStatus.DEGRADED

            logger.warning("功能恢复失败，已达最大重试次数", feature=feature)

        self._retry_tasks[feature] = asyncio.create_task(retry())

    async def recover(self, feature: str) -> bool:
        """
        手动尝试恢复功能

        Returns:
            是否恢复成功
        """
        config = self._configs.get(feature)
        if not config or not config.recovery_func:
            return False

        try:
            success = await config.recovery_func()
            if success:
                self._features[feature] = FeatureStatus.AVAILABLE
                logger.info("功能已手动恢复", feature=feature)
                self._notify_user(feature, "已恢复")
                self._notify_listeners(feature, FeatureStatus.AVAILABLE)
                return True
        except Exception as e:
            logger.debug("手动恢复失败", feature=feature, error=str(e))

        return False

    def reset(self, feature: str):
        """重置功能状态"""
        self._features[feature] = FeatureStatus.AVAILABLE
        if feature in self._retry_tasks:
            self._retry_tasks[feature].cancel()
            del self._retry_tasks[feature]


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_degradation_manager: Optional[FeatureDegradationManager] = None


def get_degradation_manager() -> FeatureDegradationManager:
    """获取功能降级管理器单例"""
    global _degradation_manager
    if _degradation_manager is None:
        _degradation_manager = FeatureDegradationManager()
    return _degradation_manager
