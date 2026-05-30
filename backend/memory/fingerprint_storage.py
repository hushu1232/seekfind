"""
求问 — 元素指纹存储
==================

参考 Scrapling 的 StorageSystemMixin + SQLiteStorageSystem 设计。

职责：
  - 存储页面元素的 selector + 描述 + 成功次数
  - 通过 URL 模式 + 描述相似度查找指纹
  - 自动清理过期指纹（30 天未使用）

存储结构（SQLite）：
  fingerprints 表：
    id            INTEGER PRIMARY KEY
    url_pattern   TEXT     -- URL 模式（如 "github.com/settings"）
    selector      TEXT     -- CSS 选择器
    xpath         TEXT     -- XPath 选择器（备选）
    description   TEXT     -- 元素描述（如 "创建项目按钮"）
    tag_name      TEXT     -- 标签名（如 "button"）
    attributes    TEXT     -- 元素属性 JSON（如 {"class": "btn-primary"}）
    success_count INTEGER  -- 成功定位次数
    fail_count    INTEGER  -- 失败次数
    created_at    REAL     -- 创建时间戳
    last_used_at  REAL     -- 最后使用时间戳

性能：
  - WAL 模式：支持并发读
  - RLock：线程安全
  - lru_cache：URL 域名提取缓存
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

# 默认数据库路径
_DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "fingerprints.db")


class FingerprintStorage:
    """
    元素指纹存储（SQLite）。

    参考 Scrapling 的 SQLiteStorageSystem：
      - WAL 模式（Write-Ahead Logging）：并发读性能好
      - RLock：可重入锁，线程安全
      - 域名隔离：不同网站的指纹分开存储

    典型用法：
        storage = FingerprintStorage()
        storage.save("github.com/settings", "#create-btn", "创建项目按钮")
        result = storage.find("https://github.com/dashboard", "创建项目按钮")
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()

        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._setup_tables()

        logger.info("指纹存储初始化", db_path=db_path)

    def _setup_tables(self):
        """创建表结构。"""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_pattern TEXT NOT NULL,
                    selector TEXT NOT NULL,
                    xpath TEXT DEFAULT '',
                    description TEXT NOT NULL,
                    tag_name TEXT DEFAULT '',
                    attributes TEXT DEFAULT '{}',
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    UNIQUE(url_pattern, selector, description)
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fp_url_pattern
                ON fingerprints(url_pattern)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fp_description
                ON fingerprints(description)
            """)
            self._conn.commit()

    def save(
        self,
        url_pattern: str,
        selector: str,
        description: str,
        xpath: str = "",
        tag_name: str = "",
        attributes: dict | None = None,
    ) -> None:
        """
        保存或更新元素指纹。

        如果 (url_pattern, selector, description) 已存在，更新 success_count 和 last_used_at。
        """
        now = time.time()
        attrs_json = json.dumps(attributes or {}, ensure_ascii=False)

        with self._lock:
            self._conn.execute("""
                INSERT INTO fingerprints
                    (url_pattern, selector, xpath, description, tag_name, attributes,
                     success_count, fail_count, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                ON CONFLICT(url_pattern, selector, description)
                DO UPDATE SET
                    success_count = success_count + 1,
                    last_used_at = ?,
                    xpath = CASE WHEN excluded.xpath != '' THEN excluded.xpath ELSE xpath END,
                    tag_name = CASE WHEN excluded.tag_name != '' THEN excluded.tag_name ELSE tag_name END,
                    attributes = CASE WHEN excluded.attributes != '{}' THEN excluded.attributes ELSE attributes END
            """, (url_pattern, selector, xpath, description, tag_name, attrs_json,
                  now, now, now))
            self._conn.commit()

        logger.debug("指纹已保存", url=url_pattern, selector=selector, desc=description)

    def find(
        self,
        url: str,
        description: str,
        min_success: int = 1,
        similarity_threshold: float = 0.6,
    ) -> dict | None:
        """
        通过 URL + 描述查找最佳匹配的指纹。

        匹配策略：
          1. 精确匹配：URL 域名 + 描述完全一致
          2. 模糊匹配：URL 域名匹配 + 描述相似度 >= threshold
          3. 按 success_count 降序，取最可靠的

        Returns:
            {"selector": "...", "xpath": "...", "description": "...", ...} 或 None
        """
        domain = self._extract_domain(url)

        with self._lock:
            # 查询同域名的所有指纹
            rows = self._conn.execute("""
                SELECT id, url_pattern, selector, xpath, description,
                       tag_name, attributes, success_count, fail_count
                FROM fingerprints
                WHERE url_pattern LIKE ?
                  AND success_count >= ?
                ORDER BY success_count DESC
            """, (f"%{domain}%", min_success)).fetchall()

        if not rows:
            return None

        # 找最佳匹配
        best_match = None
        best_score = 0.0

        for row in rows:
            fp_desc = row[4]
            # 精确匹配
            if fp_desc == description:
                score = 1.0
            else:
                # 模糊匹配
                score = SequenceMatcher(None, description.lower(), fp_desc.lower()).ratio()

            if score >= similarity_threshold and score > best_score:
                best_score = score
                best_match = {
                    "id": row[0],
                    "url_pattern": row[1],
                    "selector": row[2],
                    "xpath": row[3],
                    "description": row[4],
                    "tag_name": row[5],
                    "attributes": json.loads(row[6]) if row[6] else {},
                    "success_count": row[7],
                    "fail_count": row[8],
                    "match_score": round(score, 3),
                }

        if best_match:
            # 更新最后使用时间
            with self._lock:
                self._conn.execute(
                    "UPDATE fingerprints SET last_used_at = ? WHERE id = ?",
                    (time.time(), best_match["id"]),
                )
                self._conn.commit()
            logger.info("指纹命中", url=url, desc=description, score=best_score)

        return best_match

    def record_failure(self, fingerprint_id: int) -> None:
        """记录一次定位失败。"""
        with self._lock:
            self._conn.execute(
                "UPDATE fingerprints SET fail_count = fail_count + 1 WHERE id = ?",
                (fingerprint_id,),
            )
            self._conn.commit()

    def cleanup(self, max_age_days: int = 30) -> int:
        """
        清理过期指纹。

        删除条件：超过 max_age_days 天未使用 且 失败次数 > 成功次数。
        返回删除数量。
        """
        cutoff = time.time() - max_age_days * 86400
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM fingerprints WHERE last_used_at < ? AND fail_count > success_count",
                (cutoff,),
            )
            self._conn.commit()
            deleted = cursor.rowcount
        if deleted:
            logger.info("清理过期指纹", deleted=deleted)
        return deleted

    def get_stats(self) -> dict:
        """获取指纹库统计。"""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            reliable = self._conn.execute(
                "SELECT COUNT(*) FROM fingerprints WHERE success_count >= 2"
            ).fetchone()[0]
        return {"total": total, "reliable": reliable}

    def close(self):
        """关闭连接。"""
        with self._lock:
            self._conn.close()

    @staticmethod
    @lru_cache(maxsize=256)
    def _extract_domain(url: str) -> str:
        """从 URL 提取主域名（带缓存）。"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # 去掉端口号
            domain = domain.split(":")[0]
            return domain.lower()
        except Exception:
            return url.lower()


# 全局单例
_fingerprint_storage: FingerprintStorage | None = None


def get_fingerprint_storage(db_path: str = _DEFAULT_DB_PATH) -> FingerprintStorage:
    """获取指纹存储单例。"""
    global _fingerprint_storage
    if _fingerprint_storage is None:
        _fingerprint_storage = FingerprintStorage(db_path)
    return _fingerprint_storage
