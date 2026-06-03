"""
求问 — 配置管理模块
===================

职责：
  - 使用 pydantic-settings 从 .env 文件加载所有配置
  - 提供类型安全的配置访问
  - 支持运行时热切换（model_strategy 等）
  - T4.3: 支持企业版云端 API 备选

用法：
  from config import settings
  print(settings.ollama_model)  # "qwen2.5:7b"

配置优先级：环境变量 > .env 文件 > 代码默认值

企业部署：
  设置 MODEL_STRATEGY=enterprise 启用云端 API 备选
  当本地 Ollama 不可用时自动降级到企业 API
"""

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# 枚举：模型策略
# ---------------------------------------------------------------------------
class ModelStrategy(str, Enum):
    """
    四层模型策略：
      - LOCAL:      仅本地 Ollama 模型（零成本，适合 8GB+ 显存）
      - CLOUD:      仅云端 API（需 API Key + 联网 + 付费）
      - HYBRID:     本地优先，连续失败 N 次后自动降级云端（推荐）
      - ENTERPRISE: 企业模式，本地优先 + 云端备选（面向企业培训）
    """
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# 主配置类
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """
    求问全局配置。

    所有字段均可通过环境变量或 .env 文件覆盖。
    字段名与环境变量名一致（不区分大小写）。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- 服务端口 --------------------------------------------------------
    bff_port: int = 8700          # BFF (Backend-For-Frontend) 服务端口
    chroma_port: int = 8000       # Chroma 向量库端口（docker-compose 内部使用）

    # --- 模型策略 --------------------------------------------------------
    model_strategy: ModelStrategy = ModelStrategy.HYBRID

    # --- 本地模型 (Ollama) -----------------------------------------------
    # Ollama 提供 OpenAI 兼容的 /v1 端点，可直接用 langchain-openai 对接
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_api_key: str = ""                      # V5: 可配置 API Key（默认 "ollama"）
    ollama_model: str = "qwen2.5:7b"              # 默认推理模型
    ollama_embedding_model: str = "nomic-embed-text"  # 768 维，中英文均支持

    # --- 云端模型（HYBRID/CLOUD 模式下的兜底）-----------------------------
    cloud_api_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""       # 为空时自动禁用云端降级
    cloud_model: str = "gpt-4o-mini"

    # --- 自动降级阈值 ----------------------------------------------------
    # 连续 N 次工具调用失败后，HYBRID 模式自动切换到云端模型重试
    fallback_threshold: int = 3

    # --- T4.3: 企业模式配置（面向企业员工培训）-----------------------------
    enterprise_api_base_url: str = ""   # 企业 API 地址（如 https://api.company.com/v1）
    enterprise_api_key: str = ""        # 企业 API Key
    enterprise_model: str = ""          # 企业模型名称（如 gpt-4o）
    enterprise_auto_fallback: bool = True   # 本地不可用时自动降级
    enterprise_notify_user: bool = True     # 降级时通知用户
    enterprise_privacy_warning: bool = True # 降级时显示隐私警告

    # --- 企业部署配置 ----------------------------------------------------
    enterprise_deployment_mode: bool = False  # 企业批量部署模式
    enterprise_auto_update: bool = True       # 自动更新知识库
    enterprise_shared_knowledge: bool = True  # 共享知识库（多用户）
    enterprise_audit_log: bool = False        # 审计日志（记录所有操作）

    # --- Chroma 向量库 ---------------------------------------------------
    chroma_host: str = "chroma"   # docker-compose 服务名
    chroma_port: int = 8000
    chroma_timeout: int = 10      # 连接超时（秒）
    chroma_collection_docs: str = "qiuwen_docs"       # 文档集合
    chroma_collection_elements: str = "qiuwen_elements"  # 元素指纹集合（Phase 3）
    chroma_collection_flows: str = "qiuwen_flows"     # 操作流集合（Phase 3）

    # --- 日志 ------------------------------------------------------------
    log_level: str = "INFO"

    # --- 知识库版本（V15）-----------------------------------------------
    knowledge_version: str = "1.0.0"  # 更新知识库时递增，触发索引重建

    # --- 隐私 ------------------------------------------------------------
    privacy_sanitize_enabled: bool = True     # 自动脱敏（密码/邮箱/手机号）
    privacy_history_learning_enabled: bool = False  # 浏览历史自动学习（默认关闭）


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
settings = Settings()
