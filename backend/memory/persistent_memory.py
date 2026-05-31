"""
求问 — 持久化记忆存储
====================

参考 EverCore 的分层存储架构：
  - SQLite: 结构化数据（用户画像、成功案例、记忆元数据）
  - Chroma: 向量数据（情景记忆、原子事实、前瞻预测）

核心能力：
  - save_memory(): 保存任意类型的记忆
  - recall(): 向量检索 + 结构化过滤
  - get_profile() / update_profile(): 用户画像管理
  - save_case() / find_case(): 成功案例管理
  - cleanup(): 过期清理
"""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import structlog

from memory.types import MemoryType, MemoryRecord, UserProfile, AgentCase

logger = structlog.get_logger()

_DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "persistent_memory.db")


class PersistentMemory:
    """
    持久化记忆存储。

    SQLite 存储结构化数据，Chroma 存储向量数据。
    两者配合：结构化查询 + 语义检索。
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._setup_tables()

        logger.info("持久化记忆初始化", db_path=db_path)

    def _setup_tables(self):
        """创建表结构。"""
        with self._lock:
            # 记忆元数据表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    relevance_score REAL DEFAULT 0.0
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id)
            """)

            # 用户画像表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    products TEXT DEFAULT '[]',
                    skill_level TEXT DEFAULT 'beginner',
                    preferences TEXT DEFAULT '[]',
                    common_issues TEXT DEFAULT '[]',
                    language TEXT DEFAULT 'zh',
                    updated_at REAL NOT NULL
                )
            """)

            # 成功案例表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_cases (
                    id TEXT PRIMARY KEY,
                    question_pattern TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    url_pattern TEXT DEFAULT '',
                    success_count INTEGER DEFAULT 1,
                    fail_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_case_url ON agent_cases(url_pattern)
            """)

            self._conn.commit()

    # -----------------------------------------------------------------------
    # 记忆 CRUD
    # -----------------------------------------------------------------------

    def save_memory(self, record: MemoryRecord) -> None:
        """保存记忆记录。"""
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO memories
                    (id, type, user_id, content, metadata, created_at, accessed_at, access_count, relevance_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id, record.type.value, record.user_id,
                record.content, json.dumps(record.metadata, ensure_ascii=False),
                record.created_at, record.accessed_at,
                record.access_count, record.relevance_score,
            ))
            self._conn.commit()

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        """获取记忆。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    def search_memories(
        self,
        memory_type: MemoryType | None = None,
        user_id: str = "default",
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """搜索记忆（结构化查询）。"""
        with self._lock:
            if memory_type:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE type = ? AND user_id = ? ORDER BY accessed_at DESC LIMIT ?",
                    (memory_type.value, user_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? ORDER BY accessed_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆。"""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    # -----------------------------------------------------------------------
    # 用户画像
    # -----------------------------------------------------------------------

    def get_profile(self, user_id: str = "default") -> UserProfile | None:
        """获取用户画像。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return None
        return UserProfile(
            user_id=row[0],
            products=json.loads(row[1]) if row[1] else [],
            skill_level=row[2] or "beginner",
            preferences=json.loads(row[3]) if row[3] else [],
            common_issues=json.loads(row[4]) if row[4] else [],
            language=row[5] or "zh",
            updated_at=row[6],
        )

    def update_profile(self, profile: UserProfile) -> None:
        """更新用户画像。"""
        profile.updated_at = time.time()
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO user_profiles
                    (user_id, products, skill_level, preferences, common_issues, language, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                profile.user_id,
                json.dumps(profile.products, ensure_ascii=False),
                profile.skill_level,
                json.dumps(profile.preferences, ensure_ascii=False),
                json.dumps(profile.common_issues, ensure_ascii=False),
                profile.language,
                profile.updated_at,
            ))
            self._conn.commit()

    # -----------------------------------------------------------------------
    # 成功案例
    # -----------------------------------------------------------------------

    def save_case(self, case: AgentCase) -> None:
        """保存成功案例。"""
        if not case.id:
            case.id = hashlib.md5(
                f"{case.question_pattern}_{case.url_pattern}".encode()
            ).hexdigest()
        case.last_used_at = time.time()

        with self._lock:
            self._conn.execute("""
                INSERT INTO agent_cases (id, question_pattern, steps, url_pattern, success_count, fail_count, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    success_count = success_count + 1,
                    last_used_at = ?
            """, (
                case.id, case.question_pattern,
                json.dumps(case.steps, ensure_ascii=False),
                case.url_pattern, case.success_count, case.fail_count,
                case.created_at, case.last_used_at, case.last_used_at,
            ))
            self._conn.commit()

    def find_case(self, question_pattern: str, url_pattern: str = "") -> AgentCase | None:
        """查找相似的成功案例。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_cases WHERE success_count > fail_count ORDER BY success_count DESC LIMIT 20"
            ).fetchall()

        if not rows:
            return None

        # 简单的模式匹配
        from difflib import SequenceMatcher
        best_match = None
        best_score = 0.0

        for row in rows:
            case = self._row_to_case(row)
            score = SequenceMatcher(
                None, question_pattern.lower(), case.question_pattern.lower()
            ).ratio()

            # URL 匹配加分
            if url_pattern and case.url_pattern:
                url_score = SequenceMatcher(
                    None, url_pattern.lower(), case.url_pattern.lower()
                ).ratio()
                score = score * 0.7 + url_score * 0.3

            if score > best_score and score >= 0.5:
                best_score = score
                best_match = case

        if best_match:
            # 更新使用时间
            with self._lock:
                self._conn.execute(
                    "UPDATE agent_cases SET last_used_at = ? WHERE id = ?",
                    (time.time(), best_match.id),
                )
                self._conn.commit()

        return best_match

    def record_case_failure(self, case_id: str) -> None:
        """记录案例失败。"""
        with self._lock:
            self._conn.execute(
                "UPDATE agent_cases SET fail_count = fail_count + 1 WHERE id = ?",
                (case_id,),
            )
            self._conn.commit()

    # -----------------------------------------------------------------------
    # 清理
    # -----------------------------------------------------------------------

    def cleanup(self, max_age_days: int = 90) -> dict:
        """清理过期数据。"""
        cutoff = time.time() - max_age_days * 86400
        result = {"memories": 0, "cases": 0}

        with self._lock:
            # 清理过期记忆
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE accessed_at < ? AND access_count < 3",
                (cutoff,),
            )
            result["memories"] = cursor.rowcount

            # 清理失败案例
            cursor = self._conn.execute(
                "DELETE FROM agent_cases WHERE last_used_at < ? AND fail_count > success_count",
                (cutoff,),
            )
            result["cases"] = cursor.rowcount

            self._conn.commit()

        if sum(result.values()):
            logger.info("清理过期数据", **result)

        return result

    def get_stats(self) -> dict:
        """获取统计信息。"""
        with self._lock:
            memories = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            profiles = self._conn.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0]
            cases = self._conn.execute("SELECT COUNT(*) FROM agent_cases").fetchone()[0]
        return {"memories": memories, "profiles": profiles, "cases": cases}

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    def _row_to_memory(self, row) -> MemoryRecord:
        return MemoryRecord(
            id=row[0],
            type=MemoryType(row[1]),
            user_id=row[2],
            content=row[3],
            metadata=json.loads(row[4]) if row[4] else {},
            created_at=row[5],
            accessed_at=row[6],
            access_count=row[7],
            relevance_score=row[8],
        )

    def _row_to_case(self, row) -> AgentCase:
        return AgentCase(
            id=row[0],
            question_pattern=row[1],
            steps=json.loads(row[2]) if row[2] else [],
            url_pattern=row[3],
            success_count=row[4],
            fail_count=row[5],
            created_at=row[6],
            last_used_at=row[7],
        )

    def close(self):
        """关闭连接。"""
        with self._lock:
            self._conn.close()


# 全局单例
_persistent_memory: PersistentMemory | None = None


def get_persistent_memory(db_path: str = _DEFAULT_DB_PATH) -> PersistentMemory:
    """获取持久化记忆单例。"""
    global _persistent_memory
    if _persistent_memory is None:
        _persistent_memory = PersistentMemory(db_path)
    return _persistent_memory
