# Sprint 5 — Scrapling 强化实施计划

> 基于 `Scrapling内核学习与强化方案.md`，逐任务展开为可执行的实施步骤。

---

## 总览

| 任务 | 优先级 | 预估工时 | 依赖 | 状态 |
|------|--------|---------|------|------|
| T12: 集成 Scrapling Fetcher | P0 | 4h | 无 | ✅ |
| T13: 元素指纹存储层 | P1 | 3h | 无 | ✅ |
| T14: 指纹自动构建与查找 | P1 | 3h | T13 | ✅ |
| T15: CrawledDoc 增强 | P2 | 1h | T12 | ✅ |
| T16: 浏览器指纹伪装 | P3 | 2h | T12 | ✅ |
| T17: 工具懒加载 | P3 | 2h | 无 | ✅ |
| T18: 测试补充 | — | 3h | T12-T17 | ✅ |

**总预估：18h（约 2.5 个工作日）**

---

## T12: 集成 Scrapling Fetcher（P0）

### 目标
用 Scrapling 的 `Fetcher` / `StealthyFetcher` 替换 httpx + trafilatura，支持 JS 渲染页面和反爬。

### 12.1 修改依赖

**文件：`backend/requirements.txt`**

```diff
 # --- HTTP ---
 httpx==0.28.*

 # --- 文档清洗 ---
 trafilatura==1.12.*

+# --- Scrapling（自适应爬取 + 反检测）---
+# 核心包（不含浏览器引擎，仅 HTTP 模式）
+scrapling>=0.4.8
+# 可选：浏览器模式需要 playwright/patchright
+# scrapling[browser]>=0.4.8
```

> **注意**：Scrapling 的 HTTP 模式（`Fetcher`）基于 curl_cffi，无需安装 playwright。
> 只有 `StealthyFetcher` / `DynamicFetcher` 才需要浏览器引擎。
> 初始集成只用 HTTP 模式，避免 Docker 镜像膨胀。

### 12.2 新建 Fetcher 适配层

**新建文件：`backend/indexer/scrapling_fetcher.py`**

职责：
- 封装 Scrapling Fetcher，提供统一的 `fetch(url) → CrawledDoc` 接口
- 自动选择 Fetcher 模式（HTTP / 浏览器 / 隐身）
- 错误降级：Scrapling 失败时回退到 httpx + trafilatura

```python
"""
求问 — Scrapling Fetcher 适配层
==============================

职责：
  - 封装 Scrapling Fetcher，提供统一接口
  - 自动选择获取模式（HTTP / 浏览器 / 隐身）
  - 降级策略：Scrapling 失败时回退到 httpx + trafilatura

模式选择：
  - "http":    Fetcher（HTTP，curl_cffi，自动反检测 headers）— 默认
  - "browser": DynamicFetcher（Playwright，JS 渲染）— 需要 playwright
  - "stealth": StealthyFetcher（Playwright + patchright，反爬）— 需要 playwright

用法：
  fetcher = ScraplingFetcher(mode="http")
  doc = await fetcher.fetch("https://docs.example.com")
"""

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import structlog

from indexer.crawler import CrawledDoc

logger = structlog.get_logger()


@dataclass
class ScraplingFetcher:
    """Scrapling 爬取适配器。"""

    mode: str = "http"  # "http" / "browser" / "stealth"
    timeout: int = 30
    max_content_length: int = 8000  # 截断超长内容
    _fetcher: object = field(default=None, repr=False)
    _fallback_enabled: bool = True

    def __post_init__(self):
        self._init_fetcher()

    def _init_fetcher(self):
        """延迟初始化 Scrapling Fetcher。"""
        try:
            if self.mode == "http":
                from scrapling import Fetcher
                self._fetcher = Fetcher(auto_match=False)
            elif self.mode == "browser":
                from scrapling import DynamicFetcher
                self._fetcher = DynamicFetcher(headless=True)
            elif self.mode == "stealth":
                from scrapling import StealthyFetcher
                self._fetcher = StealthyFetcher(headless=True)
            else:
                raise ValueError(f"未知 Fetcher 模式: {self.mode}")
            logger.info("Scrapling Fetcher 初始化成功", mode=self.mode)
        except ImportError as e:
            logger.warning("Scrapling 未安装，将使用 httpx 降级", error=str(e))
            self._fetcher = None
        except Exception as e:
            logger.warning("Scrapling 初始化失败，将使用 httpx 降级", error=str(e))
            self._fetcher = None

    async def fetch(self, url: str) -> CrawledDoc:
        """
        抓取单个页面，返回 CrawledDoc。

        降级策略：
          1. Scrapling Fetcher（首选）
          2. httpx + trafilatura（降级）
        """
        # 尝试 Scrapling
        if self._fetcher:
            try:
                return await self._fetch_with_scrapling(url)
            except Exception as e:
                logger.warning("Scrapling 抓取失败，降级到 httpx", url=url, error=str(e))

        # 降级到 httpx + trafilatura
        if self._fallback_enabled:
            return await self._fetch_with_httpx(url)

        raise RuntimeError(f"抓取失败: {url}")

    async def _fetch_with_scrapling(self, url: str) -> CrawledDoc:
        """使用 Scrapling Fetcher 抓取。"""
        import asyncio

        # Scrapling Fetcher 是同步的，在线程池中运行
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self._fetcher.get(url))

        # 从 Scrapling Response 提取内容
        text = response.text if hasattr(response, "text") else ""
        title = ""
        if hasattr(response, "css"):
            title_elements = response.css("title::text").getall()
            title = title_elements[0] if title_elements else ""

        # 截断超长内容
        if len(text) > self.max_content_length:
            text = text[: self.max_content_length] + "\n...(内容过长已截断)"

        status = response.status if hasattr(response, "status") else 200

        logger.info(
            "Scrapling 抓取成功",
            url=url,
            text_len=len(text),
            status=status,
            mode=self.mode,
        )

        return CrawledDoc(
            url=url,
            title=title,
            text=text,
            depth=0,
        )

    async def _fetch_with_httpx(self, url: str) -> CrawledDoc:
        """降级：使用 httpx + trafilatura 抓取。"""
        import httpx
        import trafilatura

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        text = trafilatura.extract(html, include_links=False, include_tables=True) or ""
        title = self._extract_title(html)

        if len(text) > self.max_content_length:
            text = text[: self.max_content_length] + "\n...(内容过长已截断)"

        logger.info("httpx 降级抓取成功", url=url, text_len=len(text))

        return CrawledDoc(url=url, title=title, text=text, depth=0)

    @staticmethod
    def _extract_title(html: str) -> str:
        import re
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def extract_links(self, html: str, base_domain: str) -> list[str]:
        """从 HTML 提取同域链接（兼容旧接口）。"""
        import re
        links = []
        for match in re.finditer(r'href=["\'](.*?)["\']', html):
            href = match.group(1)
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            full_url = urljoin(f"https://{base_domain}", href)
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                links.append(full_url)
        return links[:50]
```

### 12.3 改造 crawler.py

**文件：`backend/indexer/crawler.py`**

改动点：
1. 引入 `ScraplingFetcher` 作为默认抓取器
2. 保留 httpx + trafilatura 作为降级路径
3. `CrawledDoc` 增加新字段（T15 内容合并到此处）

```diff
+from indexer.scrapling_fetcher import ScraplingFetcher
+

 @dataclass
 class DocCrawler:
     max_pages: int = 100
     max_depth: int = 3
     timeout: int = 30
     _visited: set[str] = field(default_factory=set)
+    _fetcher: ScraplingFetcher = field(default=None, repr=False)
+
+    def __post_init__(self):
+        if self._fetcher is None:
+            self._fetcher = ScraplingFetcher(mode="http", timeout=self.timeout)

     async def crawl(self, start_url: str) -> list[CrawledDoc]:
         docs: list[CrawledDoc] = []
         queue: list[tuple[str, int]] = [(start_url, 0)]
         base_domain = urlparse(start_url).netloc

-        async with httpx.AsyncClient(...) as client:
-            while queue and len(docs) < self.max_pages:
-                ...
+        while queue and len(docs) < self.max_pages:
+            url, depth = queue.pop(0)
+            if url in self._visited or depth > self.max_depth:
+                continue
+            self._visited.add(url)
+
+            try:
+                doc = await self._fetcher.fetch(url)
+                doc.depth = depth
+                if doc.text:
+                    docs.append(doc)
+            except Exception as e:
+                logger.warning("爬取失败", url=url, error=str(e))
+                continue
+
+            # 提取链接继续爬取
+            if depth < self.max_depth:
+                # Scrapling Response 可能有 css 方法
+                # 降级时用 HTML 正则提取
+                links = self._extract_links_from_doc(doc, base_domain)
+                for link in links:
+                    if link not in self._visited:
+                        queue.append((link, depth + 1))
```

### 12.4 改造 fetch_doc_page.py

**文件：`backend/tools/fetch_doc_page.py`**

改动点：
1. 引入 `ScraplingFetcher`
2. 保留 httpx 作为降级

```diff
+from indexer.scrapling_fetcher import ScraplingFetcher
+

 @dataclass
 class FetchDocPageTool:
     name: str = "fetch_doc_page"
     ...
+    _fetcher: ScraplingFetcher = None
+
+    def __post_init__(self):
+        ...
+        self._fetcher = ScraplingFetcher(mode="http")

     async def execute(self, url: str) -> str:
-        async with httpx.AsyncClient(...) as client:
-            resp = await client.get(url)
-            html = resp.text
-        text = trafilatura.extract(html, ...)
+        try:
+            doc = await self._fetcher.fetch(url)
+            if not doc.text:
+                return json.dumps({"error": "无法提取正文，页面可能是 SPA 或需要登录", "url": url})
+            return json.dumps({"url": url, "text": doc.text}, ensure_ascii=False)
+        except Exception as e:
+            return json.dumps({"error": f"抓取失败: {str(e)}", "url": url})
```

### 12.5 验收标准

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 静态页面抓取 | `fetch("https://docs.python.org")` | 返回正文 |
| SPA 页面抓取 | `fetch("https://react.dev")` | 返回非空正文（之前返回空） |
| Scrapling 未安装降级 | 卸载 scrapling 后测试 | 自动回退 httpx |
| 超时处理 | 访问慢速网站 | 30s 超时，不阻塞 |
| 内容截断 | 访问超长页面 | 截断到 8000 字符 |

---

## T13: 元素指纹存储层（P1）

### 目标
新建 SQLite 元素指纹存储，参考 Scrapling 的 `StorageSystemMixin` + `SQLiteStorageSystem`。

### 13.1 新建指纹存储模块

**新建文件：`backend/memory/fingerprint_storage.py`**

```python
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
    url_pattern   TEXT     -- URL 模式（如 "github.com/*"）
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
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
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
                CREATE INDEX IF NOT EXISTS idx_url_pattern
                ON fingerprints(url_pattern)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_description
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
        """清理过期指纹。返回删除数量。"""
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
```

### 13.2 注册到 Agent 初始化

**文件：`backend/agent.py`**

```diff
+from memory.fingerprint_storage import get_fingerprint_storage

 class QiuWenAgent:
     def __init__(self):
         ...
+        self._fingerprint_storage = None

     async def initialize(self) -> None:
         ...
+        self._fingerprint_storage = get_fingerprint_storage()
         # 注入到工具
         langchain_tools = get_langchain_tools(
             long_term_memory=self._long_term,
+            fingerprint_storage=self._fingerprint_storage,
         )
```

### 13.3 验收标准

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 创建数据库 | 首次调用 | 自动创建 `data/fingerprints.db` |
| 保存指纹 | `save(url, selector, desc)` | 数据库中有记录 |
| 精确查找 | `find(url, "创建按钮")` | 返回匹配的 selector |
| 模糊查找 | `find(url, "新建按钮")` | 返回相似度最高的 |
| 过期清理 | `cleanup(30)` | 删除 30 天未用且失败多的 |
| 统计 | `get_stats()` | 返回 total/reliable |

---

## T14: 指纹自动构建与查找（P1）

### 目标
在 `highlight_element.py` 中集成指纹查找/存储，实现"定位成功 → 自动记录 → 下次命中"的闭环。

### 14.1 改造 highlight_element.py

**文件：`backend/tools/highlight_element.py`**

改动点：
1. 新增 `page_url` 参数（需要知道当前页面 URL）
2. 执行前先查指纹库
3. 执行后自动存储指纹

```diff
 @dataclass
 class HighlightElementTool:
     name: str = "highlight_element"
     ...
+    _fingerprint_storage: object = None

     def __post_init__(self):
         self.schema = {
             "parameters": {
                 "properties": {
+                    "page_url": {
+                        "type": "string",
+                        "description": "当前页面 URL（用于指纹查找/存储）",
+                    },
                     "selector": { ... },
                     "description": { ... },
                     ...
                 },
-                "required": ["selector", "description"],
+                "required": ["selector", "description", "page_url"],
             },
         }

     async def execute(
         self,
         selector: str,
         description: str,
+        page_url: str = "",
         fallback_selector: str = None,
         order: int = 1,
         style: str = "pulse",
+        fingerprint_storage=None,
     ) -> str:
+        storage = fingerprint_storage or self._fingerprint_storage
+
+        # Layer 0: 查指纹库（如果 selector 为空，尝试从指纹库恢复）
+        if storage and page_url and (not selector or selector == "auto"):
+            fp = storage.find(page_url, description)
+            if fp:
+                selector = fp["selector"]
+                fallback_selector = fp.get("xpath") or fallback_selector
+                logger.info("指纹命中，使用缓存 selector", selector=selector, desc=description)
+
         # 原有逻辑...
         logger.info("生成高亮指令", selector=selector, ...)

+        # 自动存储指纹（成功定位后）
+        if storage and page_url and selector:
+            storage.save(
+                url_pattern=self._normalize_url(page_url),
+                selector=selector,
+                description=description,
+                xpath=fallback_selector or "",
+            )

         return json.dumps({ ... })
+
+    @staticmethod
+    def _normalize_url(url: str) -> str:
+        """URL 归一化：去掉查询参数和锚点，保留路径模式。"""
+        from urllib.parse import urlparse
+        parsed = urlparse(url)
+        # 保留域名 + 路径，去掉查询参数
+        return f"{parsed.netloc}{parsed.path}"
```

### 14.2 更新工具注册

**文件：`backend/tools/__init__.py`**

```diff
 def get_langchain_tools(
     long_term_memory=None,
     vision_model=None,
     llm=None,
+    fingerprint_storage=None,
 ) -> list[StructuredTool]:
     deps = {}
     if long_term_memory:
         deps["long_term_memory"] = long_term_memory
     if vision_model:
         deps["vision_model"] = vision_model
     if llm:
         deps["llm"] = llm
+    if fingerprint_storage:
+        deps["fingerprint_storage"] = fingerprint_storage

     _langchain_tools = [_make_langchain_tool(t, **deps) for t in _ALL_TOOLS]
     return _langchain_tools
```

### 14.3 验收标准

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 首次定位 | 调用 highlight_element(selector="#btn") | 正常返回 + 指纹入库 |
| 二次定位 | 调用 highlight_element(selector="auto", page_url=同URL) | 指纹命中，使用缓存 |
| 模糊匹配 | 描述从"创建按钮"变为"新建按钮" | 相似度匹配命中 |
| 失败记录 | 记录失败次数 | fail_count 递增 |

---

## T15: CrawledDoc 增强（P2）

### 目标
扩展 `CrawledDoc` 数据结构，增加元信息字段。

### 15.1 修改 CrawledDoc

**文件：`backend/indexer/crawler.py`**

```diff
 @dataclass
 class CrawledDoc:
     url: str
     title: str
     text: str
     depth: int = 0
+    html: str = ""              # 原始 HTML（可选，用于后续 Selector 查询）
+    status: int = 200           # HTTP 状态码
+    content_type: str = ""      # Content-Type
+    fetched_at: float = 0.0     # 抓取时间戳
+    fetcher_type: str = "http"  # 抓取方式：http / browser / stealth / fallback
```

### 15.2 更新 ScraplingFetcher 返回

在 `scrapling_fetcher.py` 的 `_fetch_with_scrapling` 和 `_fetch_with_httpx` 中填充新字段：

```python
return CrawledDoc(
    url=url,
    title=title,
    text=text,
    depth=0,
    html=html,           # 原始 HTML（Scrapling response.body 或 httpx resp.text）
    status=status,        # HTTP 状态码
    content_type=ct,      # Content-Type header
    fetched_at=time.time(),
    fetcher_type=self.mode,
)
```

### 15.3 验收标准

- 现有测试全部通过（新字段有默认值，向后兼容）
- `build_from_url` 返回的 chunk metadata 包含 `fetcher_type`

---

## T16: 浏览器指纹伪装（P3）

### 目标
参考 Scrapling 的 `fingerprints.py`，生成真实浏览器 headers。

### 16.1 新建指纹生成模块

**新建文件：`backend/indexer/fingerprints.py`**

```python
"""
求问 — 浏览器指纹生成
====================

参考 Scrapling 的 engines/toolbelt/fingerprints.py。

使用 browserforge 生成真实的浏览器指纹 headers。
如果 browserforge 未安装，回退到内置的 User-Agent 池。
"""

import random
from functools import lru_cache

import structlog

logger = structlog.get_logger()

# 内置 User-Agent 池（browserforge 不可用时的降级）
_FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


@lru_cache(maxsize=1)
def _get_header_generator():
    """延迟加载 browserforge HeaderGenerator。"""
    try:
        from browserforge.headers import HeaderGenerator, Browser
        browsers = [
            Browser(name="chrome", min_version=120),
            Browser(name="firefox", min_version=120),
            Browser(name="edge", min_version=120),
        ]
        return HeaderGenerator(
            browser=browsers,
            os=("windows", "macos", "linux"),
            device="desktop",
        )
    except ImportError:
        logger.warning("browserforge 未安装，使用内置 UA 池")
        return None


def generate_stealth_headers() -> dict:
    """
    生成真实浏览器指纹 headers。

    优先使用 browserforge，降级到内置 UA 池。
    """
    generator = _get_header_generator()
    if generator:
        try:
            headers = generator.generate()
            logger.debug("browserforge 生成 headers", ua=headers.get("User-Agent", "")[:50])
            return headers
        except Exception as e:
            logger.warning("browserforge 生成失败，降级", error=str(e))

    # 降级
    return {
        "User-Agent": random.choice(_FALLBACK_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
    }
```

### 16.2 集成到 ScraplingFetcher

在 `scrapling_fetcher.py` 的 `_fetch_with_httpx` 中使用：

```diff
+from indexer.fingerprints import generate_stealth_headers

     async def _fetch_with_httpx(self, url: str) -> CrawledDoc:
+        headers = generate_stealth_headers()
         async with httpx.AsyncClient(
             timeout=self.timeout,
             follow_redirects=True,
-            headers={"User-Agent": "Mozilla/5.0 ..."},
+            headers=headers,
         ) as client:
```

### 16.3 更新依赖

**文件：`backend/requirements.txt`**

```diff
+# --- 浏览器指纹生成（可选）---
+browserforge>=0.3.0
```

### 16.4 验收标准

| 测试项 | 方法 | 预期 |
|--------|------|------|
| browserforge 可用 | 安装 browserforge 后调用 | 返回真实 headers |
| browserforge 不可用 | 卸载后调用 | 回退到内置 UA 池 |
| UA 多样性 | 调用 10 次 | 至少 3 种不同 UA |

---

## T17: 工具懒加载（P3）

### 目标
参考 Scrapling 的 `__getattr__` 懒加载模式，减少启动开销。

### 17.1 改造 tools/__init__.py

**文件：`backend/tools/__init__.py`**

```diff
+import importlib
+
+# 懒加载注册表：工具名 → "模块路径:属性名"
+_TOOL_REGISTRY = {
+    "search_docs": "tools.search_docs:search_docs_tool",
+    "fetch_doc_page": "tools.fetch_doc_page:fetch_doc_page_tool",
+    "save_memory": "tools.memory_tools:save_memory_tool",
+    "recall_memory": "tools.memory_tools:recall_memory_tool",
+    "highlight_element": "tools.highlight_element:highlight_element_tool",
+    "visual_locate": "tools.visual_locate:visual_locate_tool",
+    "screenshot_annotate": "tools.screenshot_annotate:screenshot_annotate_tool",
+    "classify_page": "tools.classify_page:classify_page_tool",
+    "learn_flow": "tools.learn_flow:learn_flow_tool",
+}
+
+# 缓存已加载的工具实例
+_loaded_tools: dict[str, object] = {}
+
+
+def _load_tool(name: str):
+    """按需加载单个工具。"""
+    if name in _loaded_tools:
+        return _loaded_tools[name]
+
+    entry = _TOOL_REGISTRY.get(name)
+    if not entry:
+        raise KeyError(f"未知工具: {name}")
+
+    module_path, attr = entry.split(":")
+    module = importlib.import_module(module_path)
+    tool = getattr(module, attr)
+    _loaded_tools[name] = tool
+    return tool
+
+
+def get_all_tools() -> list:
+    """返回所有工具实例（按需加载）。"""
+    return [_load_tool(name) for name in _TOOL_REGISTRY]
+
+
+def get_tool_by_name(name: str):
+    """按名称获取单个工具。"""
+    return _load_tool(name)
```

### 17.2 保持向后兼容

`get_langchain_tools()` 和 `get_tool_schemas()` 内部改用 `get_all_tools()`：

```diff
-def get_langchain_tools(...) -> list[StructuredTool]:
-    ...
-    _langchain_tools = [_make_langchain_tool(t, **deps) for t in _ALL_TOOLS]
+def get_langchain_tools(...) -> list[StructuredTool]:
+    tools = get_all_tools()  # 懒加载
+    _langchain_tools = [_make_langchain_tool(t, **deps) for t in tools]
     return _langchain_tools
```

### 17.3 验收标准

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 启动不加载 | 导入 tools 模块 | 不触发工具实例化 |
| 按需加载 | 调用 `get_tool_by_name("search_docs")` | 仅加载 search_docs |
| 缓存 | 第二次调用 | 返回同一实例 |
| 全量加载 | `get_all_tools()` | 9 个工具全部返回 |

---

## T18: 测试补充

### 18.1 新建测试文件

**新建文件：`backend/tests/test_scrapling_fetcher.py`**

```python
"""ScraplingFetcher 测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from indexer.scrapling_fetcher import ScraplingFetcher


class TestScraplingFetcher:
    """ScraplingFetcher 单元测试。"""

    def test_init_http_mode(self):
        """HTTP 模式初始化。"""
        fetcher = ScraplingFetcher(mode="http")
        # 如果 scrapling 已安装，_fetcher 不为 None
        # 如果未安装，_fetcher 为 None（降级模式）
        assert fetcher.mode == "http"

    def test_init_invalid_mode(self):
        """无效模式抛出异常。"""
        with pytest.raises(ValueError):
            ScraplingFetcher(mode="invalid")

    @pytest.mark.asyncio
    async def test_fetch_fallback_to_httpx(self):
        """Scrapling 不可用时降级到 httpx。"""
        fetcher = ScraplingFetcher(mode="http")
        fetcher._fetcher = None  # 模拟 Scrapling 不可用
        fetcher._fallback_enabled = True

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = "<html><head><title>Test</title></head><body>Hello</body></html>"
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with patch("trafilatura.extract", return_value="Hello"):
                doc = await fetcher.fetch("https://example.com")
                assert doc.text == "Hello"
                assert doc.title == "Test"

    def test_extract_title(self):
        """标题提取。"""
        html = "<html><head><title>测试</title></head></html>"
        assert ScraplingFetcher._extract_title(html) == "测试"

    def test_extract_links(self):
        """链接提取。"""
        fetcher = ScraplingFetcher(mode="http")
        html = '<a href="/page1">P1</a> <a href="https://other.com">O</a>'
        links = fetcher.extract_links(html, "example.com")
        # 只保留同域链接
```

**新建文件：`backend/tests/test_fingerprint_storage.py`**

```python
"""FingerprintStorage 测试。"""

import pytest
import time
from memory.fingerprint_storage import FingerprintStorage


class TestFingerprintStorage:
    """FingerprintStorage 单元测试。"""

    @pytest.fixture
    def storage(self, tmp_path):
        """创建临时存储。"""
        db_path = str(tmp_path / "test_fingerprints.db")
        return FingerprintStorage(db_path)

    def test_save_and_find(self, storage):
        """保存后可查找。"""
        storage.save(
            url_pattern="github.com/settings",
            selector="#create-btn",
            description="创建项目按钮",
        )
        result = storage.find("https://github.com/dashboard", "创建项目按钮")
        assert result is not None
        assert result["selector"] == "#create-btn"

    def test_find_fuzzy_match(self, storage):
        """模糊匹配。"""
        storage.save(
            url_pattern="github.com/settings",
            selector="#create-btn",
            description="创建项目按钮",
        )
        # 描述不完全一致，但相似
        result = storage.find("https://github.com/dashboard", "新建项目按钮")
        assert result is not None
        assert result["match_score"] >= 0.6

    def test_find_no_match(self, storage):
        """无匹配返回 None。"""
        result = storage.find("https://github.com/dashboard", "不存在的元素")
        assert result is None

    def test_success_count_increment(self, storage):
        """重复保存递增 success_count。"""
        storage.save("github.com", "#btn", "按钮")
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://github.com", "按钮")
        assert result["success_count"] == 2

    def test_record_failure(self, storage):
        """记录失败。"""
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://github.com", "按钮")
        storage.record_failure(result["id"])
        # 查询 fail_count
        stats = storage.get_stats()
        assert stats["total"] == 1

    def test_cleanup(self, storage):
        """清理过期指纹。"""
        storage.save("github.com", "#old-btn", "旧按钮")
        # 手动设置为过期
        storage._conn.execute(
            "UPDATE fingerprints SET last_used_at = ?, fail_count = 10",
            (time.time() - 31 * 86400,),
        )
        storage._conn.commit()
        deleted = storage.cleanup(max_age_days=30)
        assert deleted == 1

    def test_get_stats(self, storage):
        """统计。"""
        storage.save("github.com", "#btn1", "按钮1")
        storage.save("github.com", "#btn2", "按钮2")
        stats = storage.get_stats()
        assert stats["total"] == 2

    def test_domain_isolation(self, storage):
        """不同域名的指纹隔离。"""
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://gitlab.com", "按钮")
        assert result is None
```

### 18.2 更新 conftest.py

**文件：`backend/tests/conftest.py`**

```diff
+@pytest.fixture
+def fingerprint_storage(tmp_path):
+    """创建临时指纹存储。"""
+    from memory.fingerprint_storage import FingerprintStorage
+    db_path = str(tmp_path / "test_fingerprints.db")
+    return FingerprintStorage(db_path)
```

### 18.3 验收标准

- 所有新增测试通过
- 现有 77 个测试不回归
- 总测试数 >= 95

---

## 依赖汇总

### 新增

```txt
# Scrapling 核心（HTTP 模式，不含 playwright）
scrapling>=0.4.8

# 浏览器指纹生成（可选，Scrapling 内部也会用到）
browserforge>=0.3.0
```

### 保留（不移除）

```txt
httpx==0.28.*       # API 调用 + Scrapling 降级路径
trafilatura==1.12.* # Scrapling 降级路径
```

---

## Docker 镜像影响

| 项目 | 现在 | 集成后 |
|------|------|--------|
| 镜像大小 | ~800MB | ~850MB（+scrapling/curl_cffi） |
| 启动时间 | ~5s | ~5s（懒加载，不影响） |
| Chromium | 无 | 无（仅用 HTTP 模式） |

> 如果后续需要 StealthyFetcher（浏览器模式），镜像会增加 ~500MB（Chromium）。
> 建议作为可选扩展，不默认启用。

---

## 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| Scrapling API 变更 | 中 | 编译失败 | pin 版本 `scrapling==0.4.*` |
| curl_cffi 在 Docker 中编译慢 | 低 | 构建时间 +2min | Docker 层缓存 |
| SQLite 锁竞争 | 低 | 高并发写入慢 | WAL + RLock，单机场景足够 |
| browserforge 下载慢 | 中 | 首次 pip install 慢 | 设为可选依赖 |

---

## 执行顺序

```
T17 (懒加载) ──────────────────────────────┐
T13 (指纹存储) ─────────────────────────────┤
                                            ├─→ T18 (测试)
T12 (Scrapling Fetcher) ──→ T15 (CrawledDoc) ┤
                                            │
T16 (指纹伪装) ─────────────────────────────┤
                                            │
T14 (指纹自动构建) ←── T13 ─────────────────┘
```

建议执行顺序：
1. **T17** — 懒加载（独立，无依赖，改完立刻验证）
2. **T13** — 指纹存储层（独立，新建文件）
3. **T14** — 指纹自动构建（依赖 T13）
4. **T12** — Scrapling Fetcher（核心改动，需要测试）
5. **T15** — CrawledDoc 增强（依赖 T12）
6. **T16** — 浏览器指纹伪装（依赖 T12）
7. **T18** — 测试补充（最后跑全量测试）
