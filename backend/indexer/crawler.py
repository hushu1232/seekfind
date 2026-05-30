"""
求问 — 文档爬虫
===============

职责：
  - 从指定 URL 开始，递归爬取同域页面
  - 使用 trafilatura 提取正文（去除导航/广告/页脚）
  - 返回结构化的 CrawledDoc 列表

爬取策略：
  - 广度优先（BFS），限制最大页数和最大深度
  - 只爬取同域链接，不外跳
  - 每页最多提取 50 个链接，防止链接爆炸
  - 30 秒超时，防止慢速网站阻塞

用法：
  crawler = DocCrawler(max_pages=100, max_depth=3)
  docs = await crawler.crawl("https://docs.example.com")
"""

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
import structlog
import trafilatura

logger = structlog.get_logger()


@dataclass
class CrawledDoc:
    """
    爬取的文档。

    Attributes:
        url: 页面 URL
        title: 页面标题（从 <title> 标签提取）
        text: 清洗后的正文文本
        depth: 距离起始 URL 的跳数（0 = 起始页）
    """
    url: str
    title: str
    text: str
    depth: int = 0


@dataclass
class DocCrawler:
    """
    文档站点爬虫。

    Attributes:
        max_pages: 最大爬取页数（防止无限爬取）
        max_depth: 最大爬取深度（从起始 URL 算起）
        timeout: 单页请求超时（秒）
        _visited: 已访问 URL 集合（去重用）
    """

    max_pages: int = 100
    max_depth: int = 3
    timeout: int = 30
    _visited: set[str] = field(default_factory=set)

    async def crawl(self, start_url: str) -> list[CrawledDoc]:
        """
        从起始 URL 开始爬取文档。

        Args:
            start_url: 起始 URL（如 "https://docs.example.com"）

        Returns:
            CrawledDoc 列表

        流程：
          1. BFS 队列初始化为 [(start_url, depth=0)]
          2. 每次取出一个 URL，请求 → 提取正文 → 记录
          3. 提取页面中的同域链接，加入队列
          4. 直到队列为空或达到 max_pages
        """
        docs: list[CrawledDoc] = []
        queue: list[tuple[str, int]] = [(start_url, 0)]
        base_domain = urlparse(start_url).netloc

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "QiuWen/0.1 (doc crawler)"},
        ) as client:
            while queue and len(docs) < self.max_pages:
                url, depth = queue.pop(0)

                # 去重 + 深度检查
                if url in self._visited or depth > self.max_depth:
                    continue
                self._visited.add(url)

                # 请求页面
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
                    logger.info("爬取成功", url=url, text_len=len(text), depth=depth)

                # 提取同域链接继续爬取
                if depth < self.max_depth:
                    links = self._extract_links(html, base_domain)
                    for link in links:
                        if link not in self._visited:
                            queue.append((link, depth + 1))

        logger.info("爬取完成", total=len(docs), visited=len(self._visited))
        return docs

    @staticmethod
    def _extract_title(html: str) -> str:
        """从 HTML <title> 标签提取页面标题。"""
        import re
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_links(html: str, base_domain: str) -> list[str]:
        """
        从 HTML 提取同域链接。

        只保留同域、http/https 协议的链接。
        每页最多返回 50 个链接，防止链接爆炸。
        """
        import re
        links = []
        for match in re.finditer(r'href=["\'](.*?)["\']', html):
            href = match.group(1)
            # 跳过锚点、javascript、mailto
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            full_url = urljoin(f"https://{base_domain}", href)
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                links.append(full_url)
        return links[:50]
