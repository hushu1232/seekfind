"""
求问 — 文档页面抓取工具
支持本地文件和远程 URL，使用 trafilatura 清洗 HTML。
"""

import json
from dataclasses import dataclass

import httpx
import structlog
import trafilatura

logger = structlog.get_logger()


@dataclass
class FetchDocPageTool:
    """文档页面抓取工具。"""

    name: str = "fetch_doc_page"
    description: str = "获取指定 URL 的页面正文内容。当需要查看具体文档页面时调用。"
    schema: dict = None

    def __post_init__(self):
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的页面 URL",
                    },
                },
                "required": ["url"],
            },
        }

    async def execute(self, url: str) -> str:
        """抓取并清洗页面正文。"""
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            # trafilatura 清洗
            text = trafilatura.extract(html, include_links=False, include_tables=True)
            if not text:
                return json.dumps({"error": "无法提取正文", "url": url})

            # 截断过长内容
            if len(text) > 8000:
                text = text[:8000] + "\n...(内容过长已截断)"

            return json.dumps({"url": url, "text": text}, ensure_ascii=False)

        except httpx.HTTPError as e:
            logger.error("抓取失败", url=url, error=str(e))
            return json.dumps({"error": f"抓取失败: {str(e)}", "url": url})


fetch_doc_page_tool = FetchDocPageTool()
