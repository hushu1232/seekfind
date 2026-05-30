"""
求问 — 配置管理
使用 pydantic-settings 从 .env 加载，类型安全。
"""

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelStrategy(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- 服务端口 ---
    bff_port: int = 8700
    chroma_port: int = 8000

    # --- 模型策略 ---
    model_strategy: ModelStrategy = ModelStrategy.HYBRID

    # --- 本地模型 (Ollama) ---
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"

    # --- 云端模型 ---
    cloud_api_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini"

    # --- 降级阈值 ---
    fallback_threshold: int = 3

    # --- Chroma ---
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_collection_docs: str = "qiuwen_docs"
    chroma_collection_elements: str = "qiuwen_elements"
    chroma_collection_flows: str = "qiuwen_flows"

    # --- 日志 ---
    log_level: str = "INFO"

    # --- 隐私 ---
    privacy_sanitize_enabled: bool = True
    privacy_history_learning_enabled: bool = False


settings = Settings()
