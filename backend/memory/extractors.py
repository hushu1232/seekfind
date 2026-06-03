"""
求问 — 记忆提取器
================

参考 EverCore 的记忆提取流水线，实现：
  - ProfileExtractor: 从对话中提取用户画像
  - CaseExtractor: 从成功的引导中提取可复用案例
  - ForesightExtractor: 基于历史预测用户需求

简化设计：
  - EverCore 使用独立 LLM 做记忆提取
  - 求问使用规则 + 关键词匹配（轻量，不依赖额外 LLM 调用）
"""

import hashlib
import re
import time

import structlog

from memory.types import AgentCase, UserProfile

logger = structlog.get_logger()


class ProfileExtractor:
    """
    用户画像提取器。

    从对话历史和页面交互中提取用户特征：
      - 常用产品
      - 技术水平
      - 操作偏好
    """

    # 产品关键词映射
    PRODUCT_KEYWORDS = {
        "GitHub": ["github", "pr", "pull request", "repository", "fork", "clone"],
        "GitLab": ["gitlab", "merge request", "ci/cd", "pipeline"],
        "VS Code": ["vscode", "vs code", "扩展", "插件", "debug", "terminal"],
        "Docker": ["docker", "容器", "镜像", "compose", "dockerfile"],
        "Kubernetes": ["k8s", "kubernetes", "pod", "deployment", "service"],
        "Jira": ["jira", "sprint", "backlog", "看板", "story"],
        "飞书": ["飞书", "feishu", "lark"],
        "钉钉": ["钉钉", "dingtalk"],
        "Notion": ["notion", "数据库", "block"],
        "Figma": ["figma", "设计", "组件", "auto layout"],
    }

    # 技术水平指标
    SKILL_INDICATORS = {
        "advanced": ["CI/CD", "pipeline", "kubernetes", "docker compose", "API", "webhook", "deploy"],
        "intermediate": ["git", "branch", "merge", "terminal", "command line", "配置"],
        "beginner": ["怎么", "如何", "什么是", "在哪里", "新手", "入门"],
    }

    def extract_from_conversation(
        self,
        messages: list[dict],
        existing_profile: UserProfile | None = None,
    ) -> UserProfile:
        """从对话历史中提取用户画像。"""
        profile = existing_profile or UserProfile()

        # 合并所有消息文本
        text = " ".join(m.get("content", "") for m in messages).lower()

        # 提取产品
        for product, keywords in self.PRODUCT_KEYWORDS.items():
            if any(kw in text for kw in keywords) and product not in profile.products:
                profile.products.append(product)

        # 提取技术水平
        for level, indicators in self.SKILL_INDICATORS.items():
            if any(ind.lower() in text for ind in indicators):
                # 只升级不降级
                levels = ["beginner", "intermediate", "advanced"]
                current_idx = levels.index(profile.skill_level)
                new_idx = levels.index(level)
                if new_idx > current_idx:
                    profile.skill_level = level

        # 提取语言偏好
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        profile.language = "zh" if chinese_chars > english_chars else "en"

        return profile

    def extract_from_page_event(self, url: str, profile: UserProfile) -> UserProfile:
        """从页面事件中提取产品信息。"""
        url_lower = url.lower()
        for product, keywords in self.PRODUCT_KEYWORDS.items():
            if any(kw in url_lower for kw in keywords) and product not in profile.products:
                profile.products.append(product)
        return profile


class CaseExtractor:
    """
    成功案例提取器。

    从成功的引导对话中提取可复用的案例。
    """

    def extract_from_feedback(
        self,
        question: str,
        steps: list[dict],
        page_url: str,
        is_correct: bool,
    ) -> AgentCase | None:
        """从反馈中提取案例。"""
        if not is_correct:
            return None

        return AgentCase(
            id=hashlib.md5(f"{question}_{page_url}".encode()).hexdigest(),
            question_pattern=self._normalize_question(question),
            steps=steps,
            url_pattern=self._extract_url_pattern(page_url),
            success_count=1,
            fail_count=0,
            created_at=time.time(),
            last_used_at=time.time(),
        )

    def _normalize_question(self, question: str) -> str:
        """归一化问题（去掉语气词、标点）。"""
        # 去掉标点和语气词
        question = re.sub(r'[？?！!。，,、]', '', question)
        question = re.sub(r'(怎么|如何|请|帮我|告诉我)\s*', '', question)
        return question.strip().lower()

    def _extract_url_pattern(self, url: str) -> str:
        """从 URL 提取模式（域名 + 路径前缀）。"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # 保留域名 + 路径第一段
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            return f"{parsed.netloc}/{path_parts[0]}*"
        return f"{parsed.netloc}/*"


class ForesightExtractor:
    """
    前瞻预测器。

    基于用户历史行为预测下一步需求。
    """

    # 产品操作 → 可能的后续需求
    FORESIGHT_MAP = {
        "github_create_repo": ["配置 CI/CD", "添加 README", "设置 Branch Protection"],
        "github_create_pr": ["代码审查", "合并 PR", "删除分支"],
        "docker_run": ["查看日志", "进入容器", "配置网络"],
        "jira_create_issue": ["设置优先级", "关联 PR", "添加评论"],
        "feishu_create_doc": ["分享文档", "设置权限", "添加评论"],
    }

    async def predict(
        self,
        recent_questions: list[str],
        current_url: str,
        products: list[str],
    ) -> list[str]:
        """预测用户可能的需求。"""
        predictions = []

        # 基于最近问题推断
        combined = " ".join(recent_questions[-3:]).lower()

        for key, suggestions in self.FORESIGHT_MAP.items():
            keywords = key.split("_")[1:]  # 去掉产品前缀
            if any(kw in combined for kw in keywords):
                predictions.extend(suggestions[:2])

        # 基于当前页面推断
        url_lower = current_url.lower()
        if "/settings" in url_lower:
            predictions.append("检查配置是否正确")
        if "/new" in url_lower or "/create" in url_lower:
            predictions.append("填写表单并提交")

        return predictions[:3]  # 最多 3 个预测
