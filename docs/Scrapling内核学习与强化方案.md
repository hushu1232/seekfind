# Scrapling 内核学习 · 求问项目强化方案

> 基于 [Scrapling](https://github.com/D4Vinci/Scrapling) (⭐ 55K+) 核心架构分析，提取可落地的设计模式，强化「求问」项目。

---

## 一、Scrapling 架构解析

### 1.1 项目定位

Scrapling 是一个自适应 Web 爬取框架，核心卖点：
- **多层 Fetcher**：HTTP → 浏览器 → 隐身浏览器，逐级升级
- **自适应选择器**：元素指纹存储 + 相似度匹配，页面改版后仍能定位
- **反检测**：浏览器指纹伪装、Cloudflare 绕过、代理轮换
- **Spider 框架**：异步优先、检查点恢复、会话管理

### 1.2 核心模块拓扑

```
scrapling/
├── fetchers/              # 获取层（3 种 Fetcher）
│   ├── requests.py        # Fetcher / AsyncFetcher（HTTP，curl_cffi）
│   ├── chrome.py          # DynamicFetcher（Playwright 普通浏览器）
│   └── stealth_chrome.py  # StealthyFetcher（Playwright + patchright 反检测）
├── parser.py              # Selector 类（lxml 封装 + 自适应选择器）
├── core/
│   ├── mixins.py          # SelectorsGeneration（CSS/XPath 自动生成）
│   ├── storage.py         # SQLiteStorageSystem（元素指纹持久化）
│   ├── custom_types.py    # TextHandler / AttributesHandler（增强类型）
│   └── translator.py      # CSS ↔ XPath 转换
├── engines/
│   ├── static.py          # HTTP 引擎（curl_cffi + 浏览器模拟）
│   ├── _browsers/
│   │   ├── _stealth.py    # 隐身浏览器引擎（patchright + Cloudflare 破解）
│   │   ├── _page.py       # 页面操作封装
│   │   └── _config_tools.py # 浏览器配置工具
│   └── toolbelt/
│       ├── fingerprints.py # 浏览器指纹生成（browserforge）
│       ├── convertor.py   # ResponseFactory（统一响应对象）
│       ├── proxy_rotation.py # 代理轮换
│       └── navigation.py  # 导航辅助
└── spiders/
    ├── spider.py          # Spider 基类（异步、检查点、会话管理）
    ├── engine.py          # CrawlerEngine（并发调度）
    └── session.py         # SessionManager（会话池）
```

### 1.3 六大设计模式

| 模式 | Scrapling 实现 | 求问可借鉴点 |
|------|---------------|-------------|
| **分层获取** | Fetcher → DynamicFetcher → StealthyFetcher | 爬虫升级：httpx → Scrapling Fetcher |
| **自适应选择器** | 指纹存储(SQLite) + 相似度匹配 + 自动重定位 | 元素指纹库自动构建 |
| **统一响应** | ResponseFactory 将不同来源转为统一 Response | 统一 CrawledDoc 接口 |
| **懒加载** | `__getattr__` 延迟导入，启动零开销 | 工具按需加载 |
| **存储抽象** | StorageSystemMixin + SQLiteStorageSystem(WAL+RLock) | 元素指纹存储层 |
| **会话管理** | SessionManager 管理多 Fetcher 会话池 | 爬虫会话复用 |

---

## 二、可落地的强化点（按优先级）

### P0：爬虫引擎升级（用 Scrapling 替换 httpx+trafilatura）

**现状问题**：
- `crawler.py` 和 `fetch_doc_page.py` 用 httpx 直接请求，无法处理 JS 渲染页面
- trafilatura 对 SPA 页面返回空
- 无反爬能力，User-Agent 固定为 `QiuWen/0.1`

**Scrapling 方案**：
```python
# 现在：httpx + trafilatura
async with httpx.AsyncClient() as client:
    resp = await client.get(url)
text = trafilatura.extract(resp.text)

# 强化后：Scrapling Fetcher（自动反检测 + JS 渲染）
from scrapling import Fetcher, StealthyFetcher

# 静态页面用 Fetcher（快，<1s）
fetcher = Fetcher(auto_match=False)
response = fetcher.get(url)
text = response.text  # 已自动提取正文

# JS 渲染页面用 StealthyFetcher（自动绕过 Cloudflare）
stealth = StealthyFetcher(headless=True)
response = stealth.fetch(url)
text = response.text
```

**改动范围**：
- `backend/indexer/crawler.py` — 替换 httpx 为 Scrapling Fetcher
- `backend/tools/fetch_doc_page.py` — 替换 httpx 为 Scrapling Fetcher
- `backend/requirements.txt` — 添加 `scrapling`

**收益**：
- 支持 JS 渲染页面（SPA 不再返回空）
- 自动反爬（Cloudflare、DataDome 等）
- 浏览器指纹伪装，降低被封概率
- 统一的 Response 对象，代码更简洁

---

### P1：自适应选择器（元素指纹自动构建）

**现状问题**：
- `highlight_element.py` 依赖 LLM 推理出 CSS selector，准确率有限
- 技术文档中规划了"元素指纹库"但未实现
- `learn_flow.py` 录制的操作流 selector 是静态的，页面改版即失效

**Scrapling 方案**：
Scrapling 的 `Selector` 类内置了：
1. **自动生成选择器**：`element.generate_css_selector` / `element.generate_xpath_selector`
2. **指纹存储**：SQLite + WAL 模式，线程安全
3. **相似度重定位**：当 selector 失效时，通过 tag+attributes+text 相似度匹配

```python
# Scrapling 的自适应选择器
from scrapling import Selector

page = Selector(html, adaptive=True, url=url)
element = page.find("button", id="create-btn")

# 自动生成 selector
css = element.generate_css_selector   # "html > body > div:nth-of-type(2) > button"
xpath = element.generate_xpath_selector  # "//body/div[2]/button"

# 自适应模式：存储元素指纹
element._storage.save(element._root, "create_button")
# 下次页面改版后，通过指纹重新定位
```

**强化方案**：

在 `highlight_element.py` 中增加指纹查找层：

```python
async def execute(self, selector, description, ...):
    # Layer 1: 查指纹库（<10ms）
    fingerprint = await self._find_fingerprint(selector, page_url)
    if fingerprint:
        return fingerprint["selector"]  # 命中缓存

    # Layer 2: 原有 selector 定位
    # Layer 3: 视觉定位降级
    ...
```

**改动范围**：
- `backend/tools/highlight_element.py` — 增加指纹查找/存储
- `backend/memory/long_term.py` — elements 集合存储指纹
- `backend/indexer/build_fingerprints.py` — 新建，指纹自动提取

---

### P2：统一响应对象（ResponseFactory 模式）

**现状问题**：
- `CrawledDoc` 只有 url/title/text/depth 四个字段
- 爬虫和 fetch_doc_page 的返回格式不统一
- 缺少 status_code、headers、cookies 等元信息

**Scrapling 方案**：
Scrapling 的 `ResponseFactory` 将 Playwright 响应、HTTP 响应、重定向历史统一为一个 `Response` 对象：

```python
# 统一接口
response.url
response.text
response.status
response.headers
response.cookies
response.selector  # 自动解析为 Selector 对象
response.css("h1")  # 直接查询
response.xpath("//title")
```

**强化方案**：

```python
@dataclass
class CrawledDoc:
    url: str
    title: str
    text: str
    html: str = ""           # 新增：原始 HTML
    status: int = 200        # 新增：HTTP 状态码
    content_type: str = ""   # 新增：内容类型
    depth: int = 0
    fetched_at: float = 0    # 新增：抓取时间戳
    fetcher_type: str = "http"  # 新增：抓取方式（http/browser/stealth）
```

---

### P3：懒加载工具（减少启动开销）

**现状问题**：
- `tools/__init__.py` 在 `get_langchain_tools()` 中实例化所有工具
- 9 个工具全部加载，即使用户只用 search_docs

**Scrapling 方案**：
Scrapling 全局使用 `__getattr__` 懒加载：

```python
_LAZY_IMPORTS = {
    "Fetcher": ("scrapling.fetchers.requests", "Fetcher"),
    "StealthyFetcher": ("scrapling.fetchers.stealth_chrome", "StealthyFetcher"),
}

def __getattr__(name):
    if name in _LAZY_IMPORTS:
        module_path, class_name = _LAZY_IMPORTS[name]
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
```

**强化方案**：
在 `tools/__init__.py` 中改为按需注册：

```python
_TOOL_REGISTRY = {
    "search_docs": "tools.search_docs:search_docs_tool",
    "fetch_doc_page": "tools.fetch_doc_page:fetch_doc_page_tool",
    "highlight_element": "tools.highlight_element:highlight_element_tool",
    ...
}

def get_tool_by_name(name: str):
    """按需加载单个工具"""
    entry = _TOOL_REGISTRY[name]
    module_path, attr = entry.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr)
```

---

### P4：存储层抽象（StorageSystemMixin 模式）

**现状问题**：
- 元素指纹、操作流、对话记忆都直接操作 Chroma
- 没有统一的存储抽象层
- Chroma 无连接池，每次查询新建连接

**Scrapling 方案**：
```python
class StorageSystemMixin(ABC):
    @abstractmethod
    def save(self, element, identifier): ...
    @abstractmethod
    def retrieve(self, identifier): ...

class SQLiteStorageSystem(StorageSystemMixin):
    # WAL 模式 + RLock + lru_cache
    connection.execute("PRAGMA journal_mode=WAL")
    self.lock = RLock()
```

**强化方案**：
为元素指纹引入 SQLite 存储（比 Chroma 更适合结构化查询）：

```python
class FingerprintStorage:
    """元素指纹存储（SQLite，参考 Scrapling StorageSystemMixin）"""

    def __init__(self, db_path: str = "fingerprints.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self._setup()

    def save(self, url_pattern: str, selector: str, fingerprint: dict):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO fingerprints VALUES (?, ?, ?, ?)",
                (url_pattern, selector, json.dumps(fingerprint), time.time())
            )
            self.conn.commit()

    def find(self, url: str, description: str) -> dict | None:
        """通过 URL 模式 + 描述相似度查找指纹"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM fingerprints WHERE url_pattern LIKE ?",
                (f"%{self._extract_domain(url)}%",)
            ).fetchall()
            # 相似度匹配
            return self._best_match(rows, description)
```

---

### P5：浏览器指纹伪装（反检测）

**现状问题**：
- 爬虫 User-Agent 固定为 `QiuWen/0.1`
- 无浏览器指纹伪装
- 遇到 Cloudflare 等反爬直接失败

**Scrapling 方案**：
```python
from scrapling.engines.toolbelt.fingerprints import generate_headers

# 自动生成真实浏览器指纹
headers = generate_headers(browser_mode=False)
# → 随机 Chrome/Firefox/Edge 的真实 User-Agent + Accept + Accept-Language 等

# curl_cffi 浏览器模拟
from curl_cffi.requests import Session
session = Session(impersonate="chrome")  # 模拟 Chrome TLS 指纹
```

**强化方案**：
在爬虫中引入浏览器指纹生成：

```python
# backend/indexer/fingerprints.py
from browserforge.headers import HeaderGenerator, Browser

def generate_stealth_headers() -> dict:
    """生成真实浏览器指纹 headers（参考 Scrapling）"""
    browsers = [
        Browser(name="chrome", min_version=120),
        Browser(name="firefox", min_version=120),
        Browser(name="edge", min_version=120),
    ]
    return HeaderGenerator(
        browser=browsers,
        os=("windows", "macos", "linux"),
        device="desktop",
    ).generate()
```

---

## 三、实施路线

### Sprint 5（Scrapling 强化）

| 任务 | 优先级 | 改动文件 | 说明 |
|------|--------|---------|------|
| T12: 集成 Scrapling Fetcher | P0 | crawler.py, fetch_doc_page.py, requirements.txt | 替换 httpx，支持 JS 渲染 + 反爬 |
| T13: 元素指纹存储层 | P1 | 新建 fingerprint_storage.py | SQLite + WAL + 相似度匹配 |
| T14: 指纹自动构建 | P1 | highlight_element.py, build_fingerprints.py | 成功定位后自动存储指纹 |
| T15: CrawledDoc 增强 | P2 | crawler.py | 添加 html/status/content_type 字段 |
| T16: 浏览器指纹伪装 | P3 | 新建 fingerprints.py | browserforge 生成真实 headers |
| T17: 工具懒加载 | P3 | tools/__init__.py | 按需加载，减少启动开销 |

### 验收标准

| 指标 | 目标 |
|------|------|
| SPA 页面抓取 | 之前返回空 → 现在返回正文 |
| Cloudflare 站点 | 之前 403 → 现在自动绕过 |
| 元素指纹命中率 | 同一页面二次访问命中率 > 80% |
| 高亮精确度 | 指纹命中时 < 100ms |
| 爬虫被封率 | 从 ~30% 降至 < 5% |

---

## 四、依赖变更

### 新增依赖

```txt
# Scrapling（替代 httpx + trafilatura 的部分场景）
scrapling>=0.4.8

# 浏览器指纹生成（Scrapling 内部依赖）
browserforge>=0.3.0
```

### 可选移除

```txt
# 如果全面采用 Scrapling Fetcher，可考虑移除：
# httpx → 保留（API 调用仍需要）
# trafilatura → 保留（简单场景仍需要，Scrapling 的 Selector 也可替代）
```

---

## 五、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Scrapling 体积大（含 playwright） | Docker 镜像 +500MB | 仅在需要时安装，用 extras_require |
| patchright 需要 Chromium | 首次启动慢 | Docker 预装，或降级为 Fetcher（HTTP） |
| SQLite 并发限制 | 高并发写入阻塞 | WAL 模式 + RLock，单机场景足够 |
| 浏览器指纹库更新 | 过期指纹反而暴露 | pin browserforge 版本，定期更新 |

---

## 六、关键代码对照

### 爬虫：现在 vs 强化后

```python
# ===== 现在：crawler.py =====
async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "QiuWen/0.1"}) as client:
    resp = await client.get(url)
    html = resp.text
text = trafilatura.extract(html)

# ===== 强化后：crawler.py =====
from scrapling import Fetcher, StealthyFetcher

class DocCrawler:
    def __init__(self, stealth: bool = False):
        self._fetcher = StealthyFetcher(headless=True) if stealth else Fetcher(auto_match=False)

    async def crawl(self, start_url: str) -> list[CrawledDoc]:
        response = self._fetcher.get(start_url)
        # response.text 自动提取正文
        # response.status 包含 HTTP 状态码
        # response.css("a") 可直接查询链接
        links = response.css("a::attr(href)").getall()
        ...
```

### 选择器：现在 vs 强化后

```python
# ===== 现在：highlight_element.py =====
async def execute(self, selector, description, ...):
    # 直接用 LLM 给出的 selector，无容错
    return json.dumps({"selector": selector})

# ===== 强化后：highlight_element.py =====
async def execute(self, selector, description, page_url, ...):
    # Layer 1: 查指纹库
    fp = self._fingerprint_storage.find(page_url, description)
    if fp and fp["success_count"] >= 2:
        return json.dumps({"selector": fp["selector"], "source": "fingerprint"})

    # Layer 2: 原始 selector
    # Layer 3: 视觉定位降级
    ...

    # 定位成功后，自动存储指纹
    self._fingerprint_storage.save(page_url, selector, {
        "description": description,
        "success_count": 1,
        "last_seen": time.time(),
    })
```
