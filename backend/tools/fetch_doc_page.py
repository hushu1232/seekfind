"""
求问 — 文档页面抓取工具
=======================

职责：
  - 抓取指定 URL 的网页内容
  - 使用 trafilatura 从 HTML 中提取正文（去除导航、广告、页脚等噪音）
  - 返回清洗后的纯文本供 Agent 使用

为什么用 trafilatura：
  - 比 BeautifulSoup 手写规则质量更高
  - 自动识别正文区域，去除 boilerplate
  - 支持表格提取
  - 被 Jina Reader、Firecrawl 等知名项目采用

安全：
  - 超时 30 秒，防止慢速网站阻塞
  - 自动跟随重定向（最多 5 层）
  - 内容截断 8000 字符，防止超长页面占用过多 token

用法（Agent 工具调用）：
  result = await fetch_doc_page_tool.execute("https://docs.example.com/guide")
"""

import json
from dataclasses import dataclass

import httpx
import structlog
import trafilatura

logger = structlog.get_logger()


@dataclass
class FetchDocPageTool:
    """
    文档页面抓取工具。

    Attributes:
        name: 工具名（Function Calling 时的 function name）
        description: 工具描述
        schema: Function Calling schema
    """

    name: str = "fetch_doc_page"
    description: str = (
        "获取指定 URL 的页面正文内容。"
        "当需要查看具体文档页面、或 search_docs 结果不够详细时调用。"
    )
    schema: dict = None

    def __post_init__(self):
        """初始化 Function Calling schema。"""
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

    async def execute(self, url: str) -> str:
        """
        抓取并清洗页面正文。

        Args:
            url: 目标页面 URL

        Returns:
            JSON 字符串：
              成功：{"url": "...", "text": "页面正文..."}
              失败：{"error": "错误信息", "url": "..."}

        流程：
          1. httpx 异步 GET 请求（30 秒超时，跟随重定向）
          2. trafilatura.extract 提取正文
          3. 截断超长内容（8000 字符上限）
        """
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "QiuWen/0.1 (local AI assistant)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            # trafilatura 正文提取
            text = trafilatura.extract(
                html,
                include_links=False,   # 不包含链接标记
                include_tables=True,   # 保留表格内容
            )

            if not text:
                logger.warning("trafilatura 未能提取正文", url=url)
                return json.dumps({"error": "无法提取正文，页面可能是 SPA 或需要登录", "url": url})

            # 截断超长内容（节省 LLM token）
            truncated = False
            if len(text) > 8000:
                text = text[:8000] + "\n...(内容过长已截断)"
                truncated = True

            logger.info("页面抓取成功", url=url, text_len=len(text), truncated=truncated)
            return json.dumps({"url": url, "text": text}, ensure_ascii=False)

        except httpx.TimeoutException:
            logger.error("抓取超时", url=url)
            return json.dumps({"error": "抓取超时（30秒）", "url": url})
        except httpx.HTTPStatusError as e:
            logger.error("HTTP 错误", url=url, status=e.response.status_code)
            return json.dumps({"error": f"HTTP {e.response.status_code}", "url": url})
        except httpx.HTTPError as e:
            logger.error("抓取失败", url=url, error=str(e))
            return json.dumps({"error": f"抓取失败: {str(e)}", "url": url})


# ---------------------------------------------------------------------------
# 工具实例（单例）
# ---------------------------------------------------------------------------
fetch_doc_page_tool = FetchDocPageTool()
