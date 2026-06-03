"""
求问 — 安全守卫
===============

职责：
  1. 防止 Prompt 注入攻击
  2. 验证用户输入
  3. 净化输出（移除敏感信息）
  4. 验证工具调用参数
  5. URL 安全验证（防止 SSRF）
  6. 速率限制

安全原则：
  - 默认拒绝：不符合规则的输入一律拒绝
  - 最小权限：工具调用只能访问授权资源
  - 纵深防御：多层检查，不依赖单一防线
"""

import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from collections import defaultdict

import structlog

logger = structlog.get_logger()


@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    is_safe: bool
    reason: str | None = None
    risk_level: str = "low"  # low, medium, high, critical
    details: dict | None = None


class SecurityGuard:
    """
    安全守卫

    提供输入验证、Prompt 注入防护、输出净化等功能。
    """

    def __init__(self):
        # Prompt 注入黑名单模式
        self._injection_patterns = [
            # 中文注入
            r"忽略.*(?:之前|上面|系统).*(?:指令|提示|规则)",
            r"(?:告诉|显示|透露).*(?:系统|初始).*(?:提示|指令)",
            r"(?:你现在|你扮演|假装).*(?:是|成为|变成)",
            r"(?:不要|别).*(?:遵守|遵循|听从).*(?:规则|指令)",
            r"(?:解除|删除|清除).*(?:限制|规则|过滤)",
            r"(?:请帮我|帮我总结).*(?:忽略|ignore).*(?:规则|rules)",

            # 英文注入
            r"ignore\s+(?:all\s+)?(?:previous|above|system)\s+(?:instructions|prompts|rules)",
            r"(?:you\s+are|you're)\s+now\s+(?:a|an|the)",
            r"(?:pretend|act|behave)\s+(?:as\s+if|like)\s+you\s+(?:are|were)",
            r"(?:reveal|show|tell\s+me)\s+(?:your|the)\s+(?:system|initial)\s+(?:prompt|instructions)",
            r"(?:override|bypass|disable)\s+(?:safety|content|security)\s+(?:filter|check|restriction)",
            r"(?:DAN|jailbreak|developer\s+mode)",
            r"do\s+anything\s+now",
            r"(?:system|initial)\s+(?:prompt|instructions)\s*(?:is|:)",
        ]

        # 敏感信息模式
        self._sensitive_patterns = {
            "email": r'[\w.-]+@[\w.-]+\.\w+',
            "phone": r'1[3-9]\d{9}',
            "id_card": r'\d{17}[\dXx]',
            "bank_card": r'\d{16,19}',
            "password": r'(?:password|passwd|pwd)\s*[:=]\s*\S+',
            "api_key": r'(?:api[_-]?key|apikey|secret)\s*[:=]\s*\S+',
        }

        # 危险命令模式
        self._dangerous_patterns = [
            r"(?:^|\s)rm\s+-rf",
            r"(?:^|\s)sudo\s+",
            r"(?:^|\s)chmod\s+777",
            r"curl\s+.*\|\s*(?:sh|bash)",
            r"wget\s+.*\|\s*(?:sh|bash)",
            r"(?:^|\s)eval\s+",
            r"(?:^|\s)exec\s+",
        ]

        # 工具白名单
        self._allowed_tools = {
            "search_docs",
            "fetch_doc_page",
            "highlight_element",
            "visual_locate",
            "screenshot_annotate",
            "classify_page",
            "learn_flow",
            "save_memory",
            "recall_memory",
            "browser_snapshot",
            "browser_interact",
            "browser_find",
        }

        # URL 白名单协议
        self._allowed_protocols = {"http://", "https://"}

        # 允许的域名（用于 fetch_doc_page）
        self._allowed_domains = {
            "github.com",
            "gitlab.com",
            "docs.google.com",
            "notion.so",
            "figma.com",
            "slack.com",
            "discord.com",
            "stackoverflow.com",
            "developer.mozilla.org",
            "w3schools.com",
            "python.org",
            "pypi.org",
            "npmjs.com",
        }

        # 内网地址前缀
        self._private_ip_prefixes = [
            "10.",
            "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.",
            "172.24.", "172.25.", "172.26.", "172.27.",
            "172.28.", "172.29.", "172.30.", "172.31.",
            "192.168.",
            "127.",
            "0.",
            "localhost",
        ]

        # 速率限制存储
        self._rate_limit_storage: dict[str, list[float]] = defaultdict(list)

    def validate_input(self, user_input: str) -> SecurityCheckResult:
        """
        验证用户输入

        Args:
            user_input: 用户输入文本

        Returns:
            SecurityCheckResult: 检查结果
        """
        # 1. 检查长度
        if len(user_input) > 2000:
            return SecurityCheckResult(
                is_safe=False,
                reason="输入过长，最大 2000 字符",
                risk_level="medium",
            )

        # 2. 检查空输入
        if not user_input.strip():
            return SecurityCheckResult(
                is_safe=False,
                reason="输入不能为空",
                risk_level="low",
            )

        # 3. 检查 Prompt 注入
        for pattern in self._injection_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.warning(
                    "检测到潜在 Prompt 注入",
                    pattern=pattern,
                    input=user_input[:100],
                )
                return SecurityCheckResult(
                    is_safe=False,
                    reason="输入包含不允许的内容",
                    risk_level="high",
                )

        # 4. 检查危险命令
        for pattern in self._dangerous_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.warning(
                    "检测到危险命令",
                    pattern=pattern,
                    input=user_input[:100],
                )
                return SecurityCheckResult(
                    is_safe=False,
                    reason="输入包含不允许的命令",
                    risk_level="high",
                )

        return SecurityCheckResult(is_safe=True)

    def sanitize_output(self, text: str) -> str:
        """
        净化输出，移除敏感信息

        Args:
            text: 输出文本

        Returns:
            str: 净化后的文本
        """
        result = text

        # 替换敏感信息
        for info_type, pattern in self._sensitive_patterns.items():
            if info_type == "email":
                result = re.sub(pattern, '***@***.com', result)
            elif info_type == "phone":
                result = re.sub(pattern, '1**********', result)
            elif info_type == "id_card":
                result = re.sub(pattern, '******************', result)
            elif info_type == "bank_card":
                result = re.sub(pattern, '****', result)
            elif info_type in ("password", "api_key"):
                result = re.sub(pattern, f'{info_type}: ****', result, flags=re.IGNORECASE)

        return result

    def validate_tool_call(self, tool_name: str, args: dict) -> SecurityCheckResult:
        """
        验证工具调用参数

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            SecurityCheckResult: 检查结果
        """
        # 1. 检查工具是否在白名单
        if tool_name not in self._allowed_tools:
            logger.warning("未知工具调用", tool=tool_name)
            return SecurityCheckResult(
                is_safe=False,
                reason=f"未知工具: {tool_name}",
                risk_level="high",
            )

        # 2. 检查特定工具的参数
        if tool_name == "fetch_doc_page":
            url = args.get("url", "")
            # 检查协议
            if not any(url.startswith(p) for p in self._allowed_protocols):
                return SecurityCheckResult(
                    is_safe=False,
                    reason="无效的 URL 协议",
                    risk_level="medium",
                )
            # 检查 URL 安全性（防止 SSRF）
            url_check = self.validate_url(url)
            if not url_check.is_safe:
                return url_check

        if tool_name == "browser_interact":
            action = args.get("action", "")
            if action not in ("click", "fill", "hover", "focus", "scroll"):
                return SecurityCheckResult(
                    is_safe=False,
                    reason=f"不允许的交互动作: {action}",
                    risk_level="medium",
                )

        if tool_name == "browser_snapshot":
            selector = args.get("selector", "")
            # 检查选择器是否包含危险字符
            if any(char in selector for char in ["<", ">", "javascript:", "on"]):
                return SecurityCheckResult(
                    is_safe=False,
                    reason="选择器包含危险字符",
                    risk_level="medium",
                )

        return SecurityCheckResult(is_safe=True)

    def validate_url(self, url: str) -> SecurityCheckResult:
        """
        验证 URL 是否安全（防止 SSRF）

        Args:
            url: URL 字符串

        Returns:
            SecurityCheckResult: 检查结果
        """
        try:
            parsed = urlparse(url)

            # 1. 检查协议
            if parsed.scheme not in ("http", "https"):
                return SecurityCheckResult(
                    is_safe=False,
                    reason=f"不允许的协议: {parsed.scheme}",
                    risk_level="high",
                )

            # 2. 检查是否是内网地址
            hostname = parsed.hostname or ""
            if self._is_private_ip(hostname):
                logger.warning("检测到内网地址访问", url=url, hostname=hostname)
                return SecurityCheckResult(
                    is_safe=False,
                    reason="不允许访问内网地址",
                    risk_level="critical",
                )

            # 3. 检查域名白名单（可选）
            # 如果需要严格限制，取消注释以下代码
            # if hostname not in self._allowed_domains:
            #     return SecurityCheckResult(
            #         is_safe=False,
            #         reason=f"域名不在白名单: {hostname}",
            #         risk_level="medium",
            #     )

            return SecurityCheckResult(is_safe=True)

        except Exception as e:
            return SecurityCheckResult(
                is_safe=False,
                reason=f"URL 解析失败: {str(e)}",
                risk_level="medium",
            )

    def _is_private_ip(self, hostname: str) -> bool:
        """
        检查是否是内网地址

        Args:
            hostname: 主机名或 IP

        Returns:
            bool: 是否是内网地址
        """
        hostname_lower = hostname.lower()

        # 检查 localhost
        if hostname_lower in ("localhost", "0.0.0.0"):
            return True

        # 检查内网 IP 前缀
        for prefix in self._private_ip_prefixes:
            if hostname_lower.startswith(prefix):
                return True

        # 检查 IPv6 内网地址
        if hostname_lower.startswith("::1") or hostname_lower.startswith("fc00"):
            return True

        return False

    def check_rate_limit(self, user_id: str, action: str, limit: int = 10, window: float = 60.0) -> bool:
        """
        检查速率限制（滑动窗口）

        Args:
            user_id: 用户 ID
            action: 动作类型
            limit: 窗口期内的最大次数
            window: 时间窗口（秒）

        Returns:
            bool: 是否允许
        """
        key = f"{user_id}:{action}"
        now = time.time()

        # 清理过期记录
        self._rate_limit_storage[key] = [
            t for t in self._rate_limit_storage[key]
            if now - t < window
        ]

        # 检查是否超过限制
        if len(self._rate_limit_storage[key]) >= limit:
            logger.warning(
                "速率限制触发",
                user_id=user_id,
                action=action,
                count=len(self._rate_limit_storage[key]),
                limit=limit,
            )
            return False

        # 记录本次请求
        self._rate_limit_storage[key].append(now)
        return True


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_security_guard: SecurityGuard | None = None


def get_security_guard() -> SecurityGuard:
    """获取安全守卫单例"""
    global _security_guard
    if _security_guard is None:
        _security_guard = SecurityGuard()
    return _security_guard
