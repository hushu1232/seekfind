"""
求问 — 文档爬虫
使用 httpx 抓取页面，trafilatura 提取正文。
"""

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
import structlog
import trafilatura

logger = structlog.get_logger()


@dataclass
class CrawledDoc:
    """爬取的文档。"""

    url: str
    title: str
    text: str
    depth: int = 0


@dataclass
class DocCrawler:
    """文档站点爬虫。"""

    max_pages: int = 100
    max_depth: int = 3
    timeout: int = 30
    _visited: set[str] = field(default_factory=set)

    async def crawl(self, start_url: str) -> list[CrawledDoc]:
        """从起始 URL 开始爬取文档。"""
        docs: list[CrawledDoc] = []
        queue: list[tuple[str, int]] = [(start_url, 0)]
        base_domain = urlparse(start_url).netloc

        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True
        ) as client:
            while queue and len(docs) < self.max_pages:
                url, depth = queue.pop(0)
                if url in self._visited or depth > self.max_depth:
                    continue
                self._visited.add(url)

                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    html = resp.text
                except httpx.HTTPError as e:
                    logger.warning("爬取失败", url=url, error=str(e))
                    continue

                # 提取正文
                text = trafilatura.extract(
                    html, include_links=False, include_tables=True
                )
                title = self._extract_title(html)
                if text:
                    docs.append(CrawledDoc(url=url, title=title, text=text, depth=depth))
                    logger.info("爬取成功", url=url, text_len=len(text))

                # 提取同域链接继续爬取
                if depth < self.max_depth:
                    links = trafilatura.extract(html, output_format="xml", include_links=True)
                    # 简化：从 HTML 中提取同域链接
                    for link in self._extract_links(html, base_domain):
                        if link not in self._visited:
                            queue.append((link, depth + 1))

        logger.info("爬取完成", total=len(docs))
        return docs

    def _extract_title(self, html: str) -> str:
        """从 HTML 提取标题。"""
        import re
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_links(self, html: str, base_domain: str) -> list[str]:
        """从 HTML 提取同域链接。"""
        import re
        links = []
        for match in re.finditer(r'href=["\'](.*?)["\']', html):
            href = match.group(1)
            full_url = urljoin(f"https://{base_domain}", href)
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                links.append(full_url)
        return links[:50]  # 限制每页最多 50 个链接
