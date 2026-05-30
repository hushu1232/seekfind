"""
求问 — Scrapling Fetcher 适配层
==============================

职责：
  - 封装 Scrapling Fetcher，提供统一的 fetch(url) → CrawledDoc 接口
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

        # 从 Scrapling Response 提取原始 HTML
        html = ""
        if hasattr(response, "body"):
            html = response.body if isinstance(response.body, str) else response.body.decode("utf-8", errors="replace")
        elif hasattr(response, "text"):
            html = response.text or ""

        # 用 trafilatura 从 HTML 提取正文（Scrapling 的 response.text 可能为空）
        text = ""
        if html:
            import trafilatura
            text = trafilatura.extract(html, include_links=False, include_tables=True) or ""

        # 如果 trafilatura 也没提取到，用 Scrapling 的 response.text
        if not text and hasattr(response, "text"):
            text = response.text or ""

        title = ""
        if hasattr(response, "css"):
            try:
                title_elements = response.css("title::text").getall()
                title = title_elements[0] if title_elements else ""
            except Exception:
                pass

        # 从 HTML 提取 title（降级）
        if not title and html:
            import re
            match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()

        status = response.status if hasattr(response, "status") else 200
        content_type = ""
        if hasattr(response, "headers"):
            content_type = response.headers.get("content-type", "") if isinstance(response.headers, dict) else ""

        # 截断超长内容
        if len(text) > self.max_content_length:
            text = text[: self.max_content_length] + "\n...(内容过长已截断)"

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
            html=html[:50000],  # 限制 HTML 大小
            status=status,
            content_type=content_type,
            fetched_at=time.time(),
            fetcher_type=f"scrapling_{self.mode}",
        )

    async def _fetch_with_httpx(self, url: str) -> CrawledDoc:
        """降级：使用 httpx + trafilatura 抓取。"""
        import httpx
        import trafilatura

        # 尝试使用 stealth headers
        try:
            from indexer.fingerprints import generate_stealth_headers
            headers = generate_stealth_headers()
        except ImportError:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
            status = resp.status_code
            content_type = resp.headers.get("content-type", "")

        text = trafilatura.extract(html, include_links=False, include_tables=True) or ""
        title = self._extract_title(html)

        if len(text) > self.max_content_length:
            text = text[: self.max_content_length] + "\n...(内容过长已截断)"

        logger.info("httpx 降级抓取成功", url=url, text_len=len(text), status=status)

        return CrawledDoc(
            url=url,
            title=title,
            text=text,
            depth=0,
            html=html[:50000],
            status=status,
            content_type=content_type,
            fetched_at=time.time(),
            fetcher_type="httpx_fallback",
        )

    @staticmethod
    def _extract_title(html: str) -> str:
        """从 HTML 提取标题。"""
        import re
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def extract_links(self, html: str, base_domain: str) -> list[str]:
        """从 HTML 提取同域链接。"""
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
