"""
求问 — 页面分类工具
===================

职责：
  - 根据 URL + DOM 快照判断页面类型
  - 双通道分类：规则匹配（快）+ LLM 分类（准）
  - 分类结果注入 Agent 上下文，辅助操作引导

页面类型：
  form       — 表单页（登录、注册、设置、提交）
  list       — 列表页（表格、目录、搜索结果）
  detail     — 详情页（文章、产品、个人资料）
  dashboard  — 仪表盘（数据概览、统计面板）
  editor     — 编辑器（代码、文档、设计）
  other      — 其他

分类策略：
  1. 规则匹配（< 5ms）：URL 模式 + DOM 特征
  2. LLM 分类（100-500ms）：规则不确定时调用

用法：
  result = await classify_page_tool.execute("https://app.example.com/dashboard", "<html>...")
"""

import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 规则库
# ---------------------------------------------------------------------------

# URL 模式 → 页面类型
URL_PATTERNS: dict[str, list[str]] = {
    "form": ["/login", "/register", "/signup", "/settings", "/profile/edit", "/new", "/create"],
    "list": ["/list", "/search", "/results", "/items", "/projects", "/issues", "/tasks"],
    "detail": ["/detail", "/view", "/article", "/post", "/product/", "/user/"],
    "dashboard": ["/dashboard", "/home", "/overview", "/analytics", "/stats"],
    "editor": ["/editor", "/edit", "/compose", "/write", "/code", "/design"],
}

# DOM 特征 → 页面类型
DOM_FEATURES: dict[str, list[str]] = {
    "form": ["<form", 'type="submit"', "login-form", "register-form", "submit-btn"],
    "list": ["<table", "data-table", "list-view", "search-result", "pagination"],
    "detail": ["article-content", "post-body", "product-detail", "user-profile"],
    "dashboard": ["dashboard", "chart", "stat-card", "metric", "overview"],
    "editor": ["editor-container", "code-mirror", "monaco-editor", "rich-text"],
}


@dataclass
class ClassifyPageTool:
    """
    页面分类工具。

    Attributes:
        name: 工具名
        description: 工具描述
        schema: Function Calling schema
    """

    name: str = "classify_page"
    description: str = (
        "判断当前页面的类型（表单/列表/详情/仪表盘/编辑器等）。"
        "用于辅助操作引导，不同页面类型有不同的引导策略。"
    )
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
                        "description": "当前页面 URL",
                    },
                    "dom_snapshot": {
                        "type": "string",
                        "description": "页面 DOM 快照（前 2000 字符）",
                    },
                },
                "required": ["url"],
            },
        }

    async def execute(self, url: str, dom_snapshot: str = "", llm=None) -> str:
        """
        执行页面分类。

        Args:
            url: 当前页面 URL
            dom_snapshot: DOM 快照（可选，提高准确度）
            llm: LLM 实例（可选，规则不确定时使用）

        Returns:
            JSON: {"page_type": "dashboard", "confidence": 0.9, "method": "rule"}
        """
        # Step 1: 规则匹配
        rule_result = self._classify_by_rules(url, dom_snapshot)
        if rule_result["confidence"] >= 0.8:
            logger.info("页面分类（规则）", url=url, type=rule_result["page_type"])
            return json.dumps(rule_result, ensure_ascii=False)

        # Step 2: LLM 分类（规则不确定时）
        if llm:
            llm_result = await self._classify_by_llm(url, dom_snapshot, llm)
            if llm_result["confidence"] > rule_result["confidence"]:
                logger.info("页面分类（LLM）", url=url, type=llm_result["page_type"])
                return json.dumps(llm_result, ensure_ascii=False)

        # 返回规则结果（即使置信度低）
        logger.info("页面分类（规则-低置信度）", url=url, type=rule_result["page_type"])
        return json.dumps(rule_result, ensure_ascii=False)

    def _classify_by_rules(self, url: str, dom_snapshot: str) -> dict:
        """规则匹配分类。"""
        scores: dict[str, float] = {}

        # URL 模式匹配
        url_lower = url.lower()
        for page_type, patterns in URL_PATTERNS.items():
            for pattern in patterns:
                if pattern in url_lower:
                    scores[page_type] = scores.get(page_type, 0) + 0.5

        # DOM 特征匹配
        dom_lower = dom_snapshot.lower()[:2000]
        for page_type, features in DOM_FEATURES.items():
            for feature in features:
                if feature in dom_lower:
                    scores[page_type] = scores.get(page_type, 0) + 0.3

        if not scores:
            return {"page_type": "other", "confidence": 0.3, "method": "rule"}

        best_type = max(scores, key=scores.get)
        confidence = min(scores[best_type], 1.0)
        return {"page_type": best_type, "confidence": confidence, "method": "rule"}

    async def _classify_by_llm(self, url: str, dom_snapshot: str, llm) -> dict:
        """LLM 分类。"""
        from langchain_core.messages import HumanMessage

        prompt = f"""判断以下页面的类型，只回复一个词：
form（表单）、list（列表）、detail（详情）、dashboard（仪表盘）、editor（编辑器）、other（其他）

URL: {url}
DOM 特征: {dom_snapshot[:500]}

页面类型："""

        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            page_type = resp.content.strip().lower()
            valid_types = ("form", "list", "detail", "dashboard", "editor", "other")
            if page_type not in valid_types:
                page_type = "other"
            return {"page_type": page_type, "confidence": 0.7, "method": "llm"}
        except Exception as e:
            logger.warning("LLM 分类失败", error=str(e))
            return {"page_type": "other", "confidence": 0.3, "method": "llm_error"}


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
classify_page_tool = ClassifyPageTool()
