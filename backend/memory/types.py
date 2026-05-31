"""
求问 — 记忆类型定义
==================

参考 EverCore 的记忆类型体系，定义求问的记忆类型：

  - EpisodeMemory: 情景记忆（完整对话上下文摘要）
  - AtomicFact: 原子事实（从对话中提取的操作知识点）
  - Foresight: 前瞻预测（基于历史推测用户需求）
  - Profile: 用户画像（累积的用户特征）
  - AgentCase: 成功引导案例（可复用的解决方案）

存储策略：
  - 结构化数据（Profile/Case）→ SQLite
  - 语义数据（Episode/Fact/Foresight）→ Chroma
"""

from enum import Enum
from dataclasses import dataclass, field
import time


class MemoryType(str, Enum):
    """记忆类型（参考 EverCore MemoryType）"""
    EPISODE = "episode"          # 情景记忆（对话上下文）
    ATOMIC_FACT = "atomic_fact"  # 原子事实（操作知识点）
    FORESIGHT = "foresight"      # 前瞻预测
    PROFILE = "profile"          # 用户画像
    AGENT_CASE = "agent_case"    # 成功引导案例


@dataclass
class MemoryRecord:
    """统一记忆记录"""
    id: str
    type: MemoryType
    content: str
    metadata: dict = field(default_factory=dict)
    user_id: str = "default"
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    relevance_score: float = 0.0


@dataclass
class UserProfile:
    """用户画像（参考 EverCore Profile）"""
    user_id: str = "default"
    products: list[str] = field(default_factory=list)        # 常用产品
    skill_level: str = "beginner"                            # beginner/intermediate/advanced
    preferences: list[str] = field(default_factory=list)     # 操作偏好
    common_issues: list[str] = field(default_factory=list)   # 常见问题
    language: str = "zh"                                     # 语言偏好
    updated_at: float = field(default_factory=time.time)


@dataclass
class AgentCase:
    """成功引导案例（参考 EverCore AgentCase）"""
    id: str = ""
    question_pattern: str = ""        # 问题模式（归一化）
    steps: list[dict] = field(default_factory=list)  # 操作步骤
    url_pattern: str = ""             # 适用的 URL 模式
    success_count: int = 1
    fail_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
