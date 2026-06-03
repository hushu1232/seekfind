"""
求问 — 多语言支持
================

职责：
  1. 语言检测
  2. 多语言 Prompt 管理
  3. 多语言知识库路由

支持语言：
  - zh: 中文（默认）
  - en: 英文
  - ja: 日文
  - ko: 韩文

使用方法：
  lang = detect_language("How to create a repository")
  prompt = get_prompt("doc", lang)
"""

from typing import Literal

import structlog

logger = structlog.get_logger()

# 支持的语言
Language = Literal["zh", "en", "ja", "ko"]

# 语言检测缓存
_language_cache: dict[str, Language] = {}


def detect_language(text: str) -> Language:
    """
    检测文本语言

    Args:
        text: 输入文本

    Returns:
        Language: 语言代码
    """
    # 检查缓存
    cache_key = text[:100]
    if cache_key in _language_cache:
        return _language_cache[cache_key]

    # 简单的语言检测规则
    lang = _detect_by_rules(text)

    # 缓存结果
    _language_cache[cache_key] = lang

    return lang


def _detect_by_rules(text: str) -> Language:
    """
    基于规则的语言检测

    Args:
        text: 输入文本

    Returns:
        Language: 语言代码
    """
    # 统计字符类型
    chinese_chars = 0
    japanese_chars = 0
    korean_chars = 0
    english_chars = 0

    for char in text:
        if '一' <= char <= '鿿':
            chinese_chars += 1
        elif '぀' <= char <= 'ゟ' or '゠' <= char <= 'ヿ':
            japanese_chars += 1
        elif '가' <= char <= '힯' or 'ᄀ' <= char <= 'ᇿ':
            korean_chars += 1
        elif 'a' <= char.lower() <= 'z':
            english_chars += 1

    # 判断主要语言
    total = chinese_chars + japanese_chars + korean_chars + english_chars
    if total == 0:
        return "zh"  # 默认中文

    # 计算比例
    chinese_ratio = chinese_chars / total
    english_ratio = english_chars / total
    japanese_ratio = japanese_chars / total
    korean_ratio = korean_chars / total

    # 返回比例最高的语言
    if chinese_ratio > 0.3:
        return "zh"
    elif english_ratio > 0.5:
        return "en"
    elif japanese_ratio > 0.3:
        return "ja"
    elif korean_ratio > 0.3:
        return "ko"
    else:
        return "zh"  # 默认中文


# ---------------------------------------------------------------------------
# 多语言 Prompt
# ---------------------------------------------------------------------------

MULTILINGUAL_PROMPTS = {
    "zh": {
        "doc": """你是求问，网页引导助手。

能力：检索文档、高亮元素、录制操作流

规则：
1. 先调用 search_docs 检索，再回答
2. 结果不详细时调用 fetch_doc_page
3. 回复简洁，不超过 100 字
4. 引用来源：📚 [文档名]
5. 不确定就说"我不确定，请导入相关文档"
""",
        "guide": """你是求问，网页引导助手。

引导规则：
1. 先调用 search_docs 检索
2. 分步引导，每步一个动作
3. 每步调用 highlight_element 高亮目标
4. 格式：📍 [动作] [目标]
5. 不确定位置时调用 visual_locate
""",
        "chat": "你是求问，友好的网页引导助手。简洁回复，不超过 50 字。",
    },
    "en": {
        "doc": """You are QiuWen, a web guidance assistant.

Capabilities: Search documents, highlight elements, record operation flows

Rules:
1. Call search_docs first, then answer
2. Call fetch_doc_page if results are insufficient
3. Keep responses concise, under 100 words
4. Cite sources: 📚 [Document Name]
5. If uncertain, say "I'm not sure, please import relevant documents"
""",
        "guide": """You are QiuWen, a web guidance assistant.

Guidance rules:
1. Call search_docs first
2. Step-by-step guidance, one action per step
3. Call highlight_element for each step
4. Format: 📍 [Action] [Target]
5. Call visual_locate if position is uncertain
""",
        "chat": "You are QiuWen, a friendly web guidance assistant. Keep responses concise, under 50 words.",
    },
    "ja": {
        "doc": """あなたはQiuWen、ウェブガイダンスアシスタントです。

能力：ドキュメント検索、要素ハイライト、操作フロー記録

ルール：
1. まずsearch_docsを呼び出してから回答
2. 結果が不十分な場合はfetch_doc_pageを呼び出し
3. 簡潔に回答、100文字以内
4. 出典を引用：📚 [ドキュメント名]
5. 不確かな場合「不明です。関連ドキュメントをインポートしてください」
""",
        "guide": """あなたはQiuWen、ウェブガイダンスアシスタントです。

ガイダンスルール：
1. まずsearch_docsを呼び出し
2. ステップバイステップのガイダンス、1ステップ1アクション
3. 各ステップでhighlight_elementを呼び出し
4. フォーマット：📍 [アクション] [ターゲット]
5. 位置が不明な場合はvisual_locateを呼び出し
""",
        "chat": "あなたはQiuWen、フレンドリーなウェブガイダンスアシスタントです。簡潔に回答、50文字以内。",
    },
    "ko": {
        "doc": """당신은 QiuWen, 웹 가이던스 어시스턴트입니다.

능력: 문서 검색, 요소 하이라이트, 작업 흐름 기록

규칙:
1. 먼저 search_docs를 호출한 후 답변
2. 결과가 불충분하면 fetch_doc_page 호출
3. 간결하게 답변, 100자 이내
4. 출처 인용: 📚 [문서명]
5. 불확실하면 "확실하지 않습니다. 관련 문서를 가져오세요"
""",
        "guide": """당신은 QiuWen, 웹 가이던스 어시스턴트입니다.

가이던스 규칙:
1. 먼저 search_docs를 호출
2. 단계별 가이던스, 한 단계에 한 동작
3. 각 단계에서 highlight_element 호출
4. 형식: 📍 [동작] [대상]
5. 위치가 불확실하면 visual_locate 호출
""",
        "chat": "당신은 QiuWen, 친근한 웹 가이던스 어시스턴트입니다. 간결하게 답변, 50자 이내.",
    },
}


def get_prompt(prompt_type: str, lang: Language = "zh") -> str:
    """
    获取多语言 Prompt

    Args:
        prompt_type: Prompt 类型 (doc, guide, chat)
        lang: 语言代码

    Returns:
        str: Prompt 文本
    """
    prompts = MULTILINGUAL_PROMPTS.get(lang, MULTILINGUAL_PROMPTS["zh"])
    return prompts.get(prompt_type, prompts["doc"])


# ---------------------------------------------------------------------------
# 多语言错误消息
# ---------------------------------------------------------------------------

MULTILINGUAL_MESSAGES = {
    "zh": {
        "error_processing": "处理查询时出错，请稍后重试",
        "error_not_safe": "输入包含不允许的内容",
        "error_too_long": "输入过长，最大 2000 字符",
        "error_empty": "输入不能为空",
        "error_timeout": "请求超时，请稍后重试",
        "thinking": "正在思考...",
        "source": "来源",
        "next_step": "下一步",
    },
    "en": {
        "error_processing": "Error processing query, please try again later",
        "error_not_safe": "Input contains disallowed content",
        "error_too_long": "Input too long, maximum 2000 characters",
        "error_empty": "Input cannot be empty",
        "error_timeout": "Request timeout, please try again later",
        "thinking": "Thinking...",
        "source": "Source",
        "next_step": "Next step",
    },
    "ja": {
        "error_processing": "クエリ処理エラー、後でもう一度お試しください",
        "error_not_safe": "入力に許可されていないコンテンツが含まれています",
        "error_too_long": "入力が長すぎます、最大2000文字",
        "error_empty": "入力は空にできません",
        "error_timeout": "リクエストタイムアウト、後でもう一度お試しください",
        "thinking": "考え中...",
        "source": "出典",
        "next_step": "次のステップ",
    },
    "ko": {
        "error_processing": "쿼리 처리 오류, 나중에 다시 시도해 주세요",
        "error_not_safe": "입력에 허용되지 않은 콘텐츠가 포함되어 있습니다",
        "error_too_long": "입력이 너무 깁니다, 최대 2000자",
        "error_empty": "입력은 비워둘 수 없습니다",
        "error_timeout": "요청 시간 초과, 나중에 다시 시도해 주세요",
        "thinking": "생각 중...",
        "source": "출처",
        "next_step": "다음 단계",
    },
}


def get_message(key: str, lang: Language = "zh") -> str:
    """
    获取多语言消息

    Args:
        key: 消息键
        lang: 语言代码

    Returns:
        str: 消息文本
    """
    messages = MULTILINGUAL_MESSAGES.get(lang, MULTILINGUAL_MESSAGES["zh"])
    return messages.get(key, key)


# ---------------------------------------------------------------------------
# 语言检测缓存管理
# ---------------------------------------------------------------------------

def clear_language_cache():
    """清空语言检测缓存"""
    global _language_cache
    _language_cache.clear()


def get_cache_stats() -> dict:
    """获取缓存统计"""
    return {
        "size": len(_language_cache),
    }
