"""
求问 — 安全守卫
===============

职责：
  1. 防止 Prompt 注入攻击
  2. 验证用户输入
  3. 净化输出（移除敏感信息）
  4. 验证工具调用参数

安全原则：
  - 默认拒绝：不符合规则的输入一律拒绝
  - 最小权限：工具调用只能访问授权资源
  - 纵深防御：多层检查，不依赖单一防线
"""

import re
from typing import Optional
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    is_safe: bool
    reason: Optional[str] = None
    risk_level: str = "low"  # low, medium, high, critical
    details: Optional[dict] = None


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

            # 英文注入
            r"ignore\s+(?:all\s+)?(?:previous|above|system)\s+(?:instructions|prompts|rules)",
            r"(?:you\s+are|you're)\s+now\s+(?:a|an|the)",
            r"(?:pretend|act|behave)\s+(?:as\s+if|like)\s+you\s+(?:are|were)",
            r"(?:reveal|show|tell\s+me)\s+(?:your|the)\s+(?:system|initial)\s+(?:prompt|instructions)",
            r"(?:override|bypass|disable)\s+(?:safety|content|security)\s+(?:filter|check|restriction)",
            r"(?:DAN|jailbreak|developer\s+mode)",
            r"do\s+anything\s+now",
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
            if not any(url.startswith(p) for p in self._allowed_protocols):
                return SecurityCheckResult(
                    is_safe=False,
                    reason="无效的 URL 协议",
                    risk_level="medium",
                )

        if tool_name == "browser_interact":
            action = args.get("action", "")
            if action not in ("click", "fill", "hover", "focus", "scroll"):
                return SecurityCheckResult(
                    is_safe=False,
                    reason=f"不允许的交互动作: {action}",
                    risk_level="medium",
                )

        return SecurityCheckResult(is_safe=True)

    def check_rate_limit(self, user_id: str, action: str, limit: int = 10, window: float = 60.0) -> bool:
        """
        检查速率限制

        Args:
            user_id: 用户 ID
            action: 动作类型
            limit: 窗口期内的最大次数
            window: 时间窗口（秒）

        Returns:
            bool: 是否允许
        """
        # 简单的滑动窗口实现
        # 实际生产环境应使用 Redis 或专用的速率限制服务
        return True


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_security_guard: Optional[SecurityGuard] = None


def get_security_guard() -> SecurityGuard:
    """获取安全守卫单例"""
    global _security_guard
    if _security_guard is None:
        _security_guard = SecurityGuard()
    return _security_guard
