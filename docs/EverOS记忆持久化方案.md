# EverOS 记忆持久化设计

> 基于 [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS) (⭐6.4K+) 的 EverCore 记忆架构，为求问设计持久化记忆系统。

---

## 一、EverCore 架构解析

### 1.1 记忆类型体系

| 类型 | 说明 | 求问适配 |
|------|------|---------|
| **EpisodeMemory** | 情景记忆（完整对话上下文） | 对话历史持久化 |
| **AtomicFact** | 原事事实（从对话中提取的知识点） | 用户学到的操作知识 |
| **Foresight** | 前瞻预测（基于历史推测用户需求） | 主动提示 |
| **Profile** | 用户画像（累积的用户特征） | 用户偏好档案 |
| **AgentCase** | Agent 案例（可复用的解决方案） | 成功引导案例 |
| **AgentSkill** | Agent 技能（可复用的操作模式） | 操作流技能 |

### 1.2 记忆提取流水线

```
原始对话/操作
    │
    ▼
MemCell 边界检测（对话分段）
    │
    ▼
记忆提取器并行工作
    ├── EpisodeMemoryExtractor → 情景记忆
    ├── AtomicFactExtractor → 原子事实
    ├── ForesightExtractor → 前瞻预测
    ├── ProfileExtractor → 用户画像
    ├── AgentCaseExtractor → 案例
    └── AgentSkillExtractor → 技能
    │
    ▼
向量化 → 存储（Chroma/Milvus）
    │
    ▼
检索 → 重排序 → 返回
```

### 1.3 核心设计原则

1. **多层记忆**：短期（对话上下文）+ 长期（向量检索）+ 持久化（结构化存储）
2. **自动提取**：从对话中自动提取知识点、用户偏好、成功案例
3. **自进化**：Agent 从成功/失败中学习，越用越准
4. **多租户**：每个用户独立的记忆空间

---

## 二、求问记忆系统现状

### 2.1 已有模块

| 模块 | 文件 | 能力 | 存储 |
|------|------|------|------|
| 短期记忆 | short_term.py | 最近 100 条对话 | 内存 deque |
| 长期记忆 | long_term.py | 向量检索 + 保存/回忆 | Chroma |
| 指纹存储 | fingerprint_storage.py | 元素 selector 指纹 | SQLite |
| 操作流 | learn_flow.py | 录制/回放操作流 | Chroma flows |

### 2.2 缺失能力

| 能力 | 说明 | EverCore 参考 |
|------|------|--------------|
| **用户画像** | 用户偏好、常用产品、技术水平 | Profile |
| **成功案例** | 成功引导的案例可复用 | AgentCase |
| **前瞻预测** | 基于历史预测用户下一步 | Foresight |
| **对话摘要** | 长对话自动摘要压缩 | EpisodeMemory |
| **知识提取** | 从对话中提取操作知识点 | AtomicFact |

---

## 三、适配方案

### 3.1 记忆类型定义

```python
# backend/memory/types.py

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import time


class MemoryType(str, Enum):
    """记忆类型（参考 EverCore MemoryType）"""
    EPISODE = "episode"          # 情景记忆（对话上下文）
    ATOMIC_FACT = "atomic_fact"  # 原子事实（操作知识点）
    FORESIGHT = "foresight"      # 前瞻预测（用户可能需要什么）
    PROFILE = "profile"          # 用户画像
    AGENT_CASE = "agent_case"    # 成功引导案例
    AGENT_SKILL = "agent_skill"  # 操作流技能


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
```

### 3.2 用户画像提取器

```python
# backend/memory/profile_extractor.py

"""
从对话历史中提取用户画像。

参考 EverCore ProfileExtractor，
使用 LLM 从对话中提取：
  - 常用产品（GitHub, VS Code, etc.）
  - 技术水平（初级/中级/高级）
  - 操作偏好（键盘党/鼠标党）
  - 常见问题模式
"""

class ProfileExtractor:
    def __init__(self, llm):
        self._llm = llm

    async def extract(self, conversation: list[dict]) -> dict:
        """从对话中提取用户画像。"""
        prompt = f"""分析以下对话，提取用户画像：
{self._format_conversation(conversation)}

返回 JSON:
{{
  "products": ["GitHub", "VS Code"],  // 常用产品
  "skill_level": "intermediate",       // beginner/intermediate/advanced
  "preferences": ["keyboard"],         // 操作偏好
  "common_issues": ["PR创建"],         // 常见问题
  "language": "zh"                     // 语言偏好
}}"""
        ...
```

### 3.3 成功案例提取器

```python
# backend/memory/case_extractor.py

"""
从成功的引导对话中提取可复用的案例。

当用户反馈"指对了"时，将该引导过程存储为 AgentCase。
下次遇到类似问题时，优先复用已知案例。
"""

class CaseExtractor:
    async def extract_from_feedback(
        self,
        question: str,
        steps: list[dict],
        page_url: str,
        is_correct: bool,
    ) -> dict | None:
        """从反馈中提取案例。"""
        if not is_correct:
            return None

        return {
            "question_pattern": self._normalize_question(question),
            "steps": steps,
            "url_pattern": self._extract_url_pattern(page_url),
            "success_count": 1,
            "created_at": time.time(),
        }

    async def find_similar_case(
        self,
        question: str,
        url: str,
    ) -> dict | None:
        """查找相似的成功案例。"""
        ...
```

### 3.4 前瞻预测器

```python
# backend/memory/foresight_extractor.py

"""
基于用户历史行为预测下一步需求。

例如：
  - 用户刚创建了 GitHub 仓库 → 可能需要配置 CI/CD
  - 用户刚打开了 Jira 看板 → 可能需要创建 Issue
  - 用户连续 3 次问同一产品 → 可能需要导入该产品文档
"""

class ForesightExtractor:
    async def predict(
        self,
        recent_questions: list[str],
        current_page: str,
        user_profile: dict,
    ) -> list[dict]:
        """预测用户可能的需求。"""
        ...
```

---

## 四、存储层设计

### 4.1 统一记忆存储

```python
# backend/memory/persistent_memory.py

"""
持久化记忆存储。

参考 EverCore 的分层存储架构：
  - SQLite：结构化数据（用户画像、案例、技能）
  - Chroma：向量数据（情景记忆、原子事实）
  - 两者配合：结构化查询 + 语义检索
"""

class PersistentMemory:
    def __init__(self, db_path: str, chroma_host: str):
        self._sqlite = sqlite3.connect(db_path)
        self._chroma = chromadb.HttpClient(host=chroma_host)
        self._setup_tables()

    def _setup_tables(self):
        """创建记忆表。"""
        self._sqlite.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at REAL,
                accessed_at REAL,
                access_count INTEGER DEFAULT 0,
                relevance_score REAL DEFAULT 0.0
            )
        """)
        self._sqlite.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                products TEXT,
                skill_level TEXT,
                preferences TEXT,
                common_issues TEXT,
                language TEXT,
                updated_at REAL
            )
        """)
        self._sqlite.execute("""
            CREATE TABLE IF NOT EXISTS agent_cases (
                id TEXT PRIMARY KEY,
                question_pattern TEXT,
                steps TEXT,
                url_pattern TEXT,
                success_count INTEGER DEFAULT 1,
                fail_count INTEGER DEFAULT 0,
                created_at REAL,
                last_used_at REAL
            )
        """)

    async def save_memory(self, record: MemoryRecord) -> None:
        """保存记忆。"""
        ...

    async def recall(
        self,
        query: str,
        memory_type: MemoryType | None = None,
        top_k: int = 5,
    ) -> list[MemoryRecord]:
        """回忆记忆（向量检索 + 结构化过滤）。"""
        ...

    async def get_profile(self, user_id: str) -> dict | None:
        """获取用户画像。"""
        ...

    async def find_similar_case(
        self,
        question: str,
        url: str,
    ) -> dict | None:
        """查找相似的成功案例。"""
        ...
```

---

## 五、集成到 Agent

### 5.1 Agent 工具扩展

```python
# 新增工具

@mcp.tool()
async def save_memory(key: str, content: str) -> str:
    """保存重要信息到长期记忆。"""
    ...

@mcp.tool()
async def recall_memory(query: str) -> str:
    """从长期记忆中搜索相关信息。"""
    ...

@mcp.tool()
async def get_user_profile() -> str:
    """获取用户画像（常用产品、技术水平等）。"""
    ...

@mcp.tool()
async def find_similar_case(question: str, url: str) -> str:
    """查找类似问题的成功引导案例。"""
    ...
```

### 5.2 Agent 流程增强

```
用户提问
    │
    ▼
获取用户画像（Profile）→ 注入上下文
    │
    ▼
查找相似案例（AgentCase）→ 如命中则复用
    │
    ▼
正常 RAG 流程
    │
    ▼
用户反馈"指对了" → 存储为 AgentCase
    │
    ▼
更新用户画像（Profile）
```

---

## 六、实施计划

| 任务 | 优先级 | 工时 | 说明 |
|------|--------|------|------|
| T28: 记忆类型定义 | P0 | 1h | types.py + MemoryRecord |
| T29: 持久化存储层 | P0 | 3h | SQLite + Chroma 统一封装 |
| T30: 用户画像提取 | P1 | 2h | 从对话中提取 Profile |
| T31: 成功案例存储 | P1 | 2h | 反馈 → AgentCase |
| T32: 前瞻预测 | P2 | 2h | 基于历史预测需求 |
| T33: Agent 集成 | P1 | 3h | 工具 + 流程增强 |
| T34: 测试 | — | 2h | 新增测试 |

**总工时：15h**
