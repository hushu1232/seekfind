"""
求问 — 文档页面抓取工具
=======================

职责：
  - 抓取指定 URL 的网页内容
  - 使用 ScraplingFetcher 提取正文（支持 JS 渲染 + 反爬）
  - 降级到 httpx + trafilatura
  - 返回清洗后的纯文本供 Agent 使用

安全：
  - 超时 30 秒，防止慢速网站阻塞
  - 自动跟随重定向（最多 5 层）
  - 内容截断 8000 字符，防止超长页面占用过多 token

用法（Agent 工具调用）：
  result = await fetch_doc_page_tool.execute("https://docs.example.com/guide")
"""

import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class FetchDocPageTool:
    """
    文档页面抓取工具。

    使用 ScraplingFetcher 进行页面抓取，支持 JS 渲染和反爬。
    如果 Scrapling 不可用，自动降级到 httpx + trafilatura。

    Attributes:
        name: 工具名（Function Calling 时的 function name）
        description: 工具描述
        schema: Function Calling schema
        _fetcher: ScraplingFetcher 实例
    """

    name: str = "fetch_doc_page"
    description: str = (
        "获取指定 URL 的页面正文内容。"
        "当需要查看具体文档页面、或 search_docs 结果不够详细时调用。"
    )
    schema: dict = None
    _fetcher: object = None

    def __post_init__(self):
        """初始化 Function Calling schema 和 Fetcher。"""
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的页面 URL（必须是完整的 http/https 地址）",
                    },
                },
                "required": ["url"],
            },
        }
        # 延迟初始化 Fetcher
        if self._fetcher is None:
            from indexer.scrapling_fetcher import ScraplingFetcher
            self._fetcher = ScraplingFetcher(mode="http")

    async def execute(self, url: str) -> str:
        """
        抓取并清洗页面正文。

        Args:
            url: 目标页面 URL

        Returns:
            JSON 字符串：
              成功：{"url": "...", "text": "页面正文...", "status": 200, "fetcher": "scrapling_http"}
              失败：{"error": "错误信息", "url": "..."}
        """
        try:
            doc = await self._fetcher.fetch(url)

            if not doc.text:
                logger.warning("未能提取正文", url=url)
                return json.dumps({
                    "error": "无法提取正文，页面可能是 SPA 或需要登录",
                    "url": url,
                })

            logger.info(
                "页面抓取成功",
                url=url,
                text_len=len(doc.text),
                status=doc.status,
                fetcher=doc.fetcher_type,
            )
            return json.dumps({
                "url": url,
                "text": doc.text,
                "status": doc.status,
                "fetcher": doc.fetcher_type,
            }, ensure_ascii=False)

        except Exception as e:
            logger.error("抓取失败", url=url, error=str(e))
            return json.dumps({"error": f"抓取失败: {str(e)}", "url": url})


# ---------------------------------------------------------------------------
# 工具实例（单例）
# ---------------------------------------------------------------------------
fetch_doc_page_tool = FetchDocPageTool()
