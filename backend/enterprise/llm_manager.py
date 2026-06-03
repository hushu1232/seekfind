"""
求问 — 企业版 LLM 管理器
========================

T4.3: 云端 API 作为企业备选方案

职责：
  1. 管理本地 Ollama 和企业 API 的切换
  2. 本地不可用时自动降级到企业 API
  3. 降级时通知用户（隐私警告）
  4. 记录降级日志（审计）

企业部署场景：
  - 企业内部培训
  - 新员工入职引导
  - 多用户共享知识库

配置：
  MODEL_STRATEGY=enterprise
  ENTERPRISE_API_BASE_URL=https://api.company.com/v1
  ENTERPRISE_API_KEY=sk-xxx
  ENTERPRISE_MODEL=gpt-4o
"""

import asyncio
from enum import Enum
from typing import Optional

import httpx
import structlog
from langchain_openai import ChatOpenAI

from config import settings

logger = structlog.get_logger()


class LLMSource(str, Enum):
    """LLM 来源"""
    LOCAL = "local"
    ENTERPRISE = "enterprise"


class EnterpriseLLMManager:
    """
    企业版 LLM 管理器

    管理本地 Ollama 和企业 API 的切换
    """

    def __init__(self):
        self._local_llm: Optional[ChatOpenAI] = None
        self._enterprise_llm: Optional[ChatOpenAI] = None
        self._current_source: LLMSource = LLMSource.LOCAL
        self._local_failures: int = 0
        self._fallback_threshold: int = settings.fallback_threshold
        self._last_check_time: float = 0
        self._local_available: bool = True

        self._initialize()

    def _initialize(self):
        """初始化 LLM 实例"""

        # 本地 LLM
        self._local_llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key or "ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )

        # 企业 LLM（如果配置了）
        if settings.enterprise_api_base_url and settings.enterprise_api_key:
            self._enterprise_llm = ChatOpenAI(
                base_url=settings.enterprise_api_base_url,
                api_key=settings.enterprise_api_key,
                model=settings.enterprise_model or "gpt-4o",
                streaming=True,
                temperature=0.7,
            )
            logger.info(
                "企业 LLM 已配置",
                base_url=settings.enterprise_api_base_url,
                model=settings.enterprise_model,
            )
        else:
            logger.info("企业 LLM 未配置，仅使用本地模型")

    async def check_local_available(self) -> bool:
        """检查本地 Ollama 是否可用"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:11434/api/tags",
                    timeout=2.0,
                )
                self._local_available = response.status_code == 200
                return self._local_available
        except Exception:
            self._local_available = False
            return False

    async def get_llm(self) -> tuple[ChatOpenAI, LLMSource]:
        """
        获取当前可用的 LLM

        Returns:
            (llm, source) 元组
        """
        # 检查是否需要降级
        if self._should_fallback():
            if self._enterprise_llm:
                logger.warning(
                    "本地模型不可用，降级到企业 API",
                    failures=self._local_failures,
                )
                self._current_source = LLMSource.ENTERPRISE
                return self._enterprise_llm, LLMSource.ENTERPRISE

        # 默认使用本地
        self._current_source = LLMSource.LOCAL
        return self._local_llm, LLMSource.LOCAL

    def _should_fallback(self) -> bool:
        """判断是否应该降级"""
        # 连续失败次数达到阈值
        if self._local_failures >= self._fallback_threshold:
            return True

        # 本地不可用
        if not self._local_available:
            return True

        return False

    def record_local_failure(self):
        """记录本地模型失败"""
        self._local_failures += 1
        logger.debug("本地模型失败", failures=self._local_failures)

    def record_local_success(self):
        """记录本地模型成功，重置失败计数"""
        if self._local_failures > 0:
            self._local_failures = 0
            self._current_source = LLMSource.LOCAL

    def get_current_source(self) -> LLMSource:
        """获取当前 LLM 来源"""
        return self._current_source

    def is_enterprise_configured(self) -> bool:
        """检查企业 API 是否已配置"""
        return self._enterprise_llm is not None

    def get_status(self) -> dict:
        """获取管理器状态"""
        return {
            "current_source": self._current_source.value,
            "local_failures": self._local_failures,
            "local_available": self._local_available,
            "enterprise_configured": self.is_enterprise_configured(),
            "fallback_threshold": self._fallback_threshold,
        }

    def reset(self):
        """重置状态"""
        self._local_failures = 0
        self._current_source = LLMSource.LOCAL
        self._local_available = True


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_enterprise_llm_manager: Optional[EnterpriseLLMManager] = None


def get_enterprise_llm_manager() -> EnterpriseLLMManager:
    """获取企业版 LLM 管理器单例"""
    global _enterprise_llm_manager
    if _enterprise_llm_manager is None:
        _enterprise_llm_manager = EnterpriseLLMManager()
    return _enterprise_llm_manager
