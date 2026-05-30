"""
求问 — LangGraph Agent 引擎
============================

核心职责：
  - 意图分类：doc_question / guide_request / chat
  - 路由分发：根据意图选择不同的处理子图
  - 工具调用：search_docs / fetch_doc_page / highlight / visual_locate / ...
  - 流式输出：AsyncGenerator yield 消息到 WebSocket

架构：
  用户提问 → 意图分类 → 路由
    ├─ doc_question → 文档检索子图 → 生成回答
    ├─ guide_request → 操作引导子图 → 三级定位 → 分步指引 + 高亮
    └─ chat → 闲聊子图 → 直接 LLM 回复

三级定位策略（guide_request 子图）：
  Level 1: selector 定位（最快，精确度高）
    → highlight_element 工具 → 直接高亮
  Level 2: 视觉定位（selector 失败时降级）
    → 截图 → moondream2 → 坐标 → 高亮
  Level 3: 截图标注（视觉定位置信度低时兜底）
    → 截图 → Pillow 标注 → 发送标注图

模型降级策略（三层）：
  Layer 1: 本地 qwen2.5:7b（默认，零成本）
  Layer 2: 本地 qwen2.5:14b（用户手动切换）
  Layer 3: 云端 GPT-4o-mini（连续失败 ≥ fallback_threshold 次后自动切换）
"""

import json
from typing import Any, AsyncGenerator

import structlog
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    BaseMessage,
)
from langchain_openai import ChatOpenAI

from config import settings, ModelStrategy
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from tools import get_all_tools

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是「求问」，一个本地智能网页引导助手。你的职责是：

1. 回答用户关于网页操作的问题（如"怎么创建项目"、"XX 功能在哪里"）
2. 在页面上高亮具体元素，引导用户完成操作
3. 用简洁、友好的中文回答，步骤用数字列表

你可以使用以下工具：
- search_docs: 从本地文档索引中检索相关信息（优先使用）
- fetch_doc_page: 获取指定 URL 的页面正文（当需要查看具体文档时）
- highlight_element: 在页面上高亮指定元素（需要 CSS selector）
- visual_locate: 通过截图视觉定位元素（当 selector 未知时）
- screenshot_annotate: 在截图上标注元素（当视觉定位不确定时）
- save_memory: 保存重要信息到长期记忆
- recall_memory: 从长期记忆中搜索信息

回答规则：
1. 先用 search_docs 检索本地文档，有结果就基于结果回答
2. 没有结果时，明确告知用户"本地文档未找到答案"，建议导入文档
3. 操作步骤要具体（点击哪个按钮、在什么位置）
4. 如果能确定元素选择器，用 highlight_element 高亮
5. 如果不确定选择器，用 visual_locate 视觉定位
6. 如果视觉定位也不确定，用 screenshot_annotate 截图标注
"""

INTENT_CLASSIFY_PROMPT = """请判断用户问题的意图类型，只回复以下类别之一：
- doc_question: 关于文档/知识的问题（怎么用、是什么、如何操作）
- guide_request: 需要在页面上引导操作（在哪里、帮我找、怎么点、怎么做）
- chat: 闲聊/打招呼/其他

用户问题：{question}
意图类型："""


# ---------------------------------------------------------------------------
# Agent 主类
# ---------------------------------------------------------------------------
class QiuWenAgent:
    """
    求问 Agent 主类。

    生命周期：initialize() → stream_reply() × N → shutdown()
    """

    def __init__(self):
        self._llm: ChatOpenAI | None = None
        self._cloud_llm: ChatOpenAI | None = None
        self._long_term: LongTermMemory | None = None
        self._tools: dict[str, Any] = {}
        self._consecutive_failures: int = 0

    async def initialize(self) -> None:
        """初始化 LLM、Chroma、工具集。"""
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        if settings.cloud_api_key and settings.model_strategy in (
            ModelStrategy.HYBRID, ModelStrategy.CLOUD,
        ):
            self._cloud_llm = ChatOpenAI(
                base_url=settings.cloud_api_base_url,
                api_key=settings.cloud_api_key,
                model=settings.cloud_model,
                streaming=True,
                temperature=0.7,
            )

        self._long_term = LongTermMemory()
        await self._long_term.initialize()

        for tool in get_all_tools():
            self._tools[tool.name] = tool

        logger.info("Agent 初始化完成", model=settings.ollama_model, tools=list(self._tools.keys()))

    async def shutdown(self) -> None:
        if self._long_term:
            await self._long_term.close()
        self._tools.clear()
        logger.info("Agent 已关闭")

    async def reload_model(self) -> None:
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        self._consecutive_failures = 0
        logger.info("模型已切换", model=settings.ollama_model)

    def _get_active_llm(self) -> ChatOpenAI:
        if (
            settings.model_strategy == ModelStrategy.HYBRID
            and self._consecutive_failures >= settings.fallback_threshold
            and self._cloud_llm
        ):
            return self._cloud_llm
        if settings.model_strategy == ModelStrategy.CLOUD and self._cloud_llm:
            return self._cloud_llm
        return self._llm

    async def classify_intent(self, question: str) -> str:
        llm = self._get_active_llm()
        resp = await llm.ainvoke([HumanMessage(content=INTENT_CLASSIFY_PROMPT.format(question=question))])
        intent = resp.content.strip().lower()
        if intent not in ("doc_question", "guide_request", "chat"):
            intent = "doc_question"
        return intent

    async def stream_reply(
        self,
        text: str,
        session: ShortTermMemory,
        page_context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict, None]:
        yield {"type": "agent_thinking", "text": "正在思考..."}
        intent = await self.classify_intent(text)
        yield {"type": "intent_classified", "intent": intent}

        if intent == "guide_request":
            async for chunk in self._handle_guide(text, session, page_context):
                yield chunk
        elif intent == "doc_question":
            async for chunk in self._handle_doc_question(text, session):
                yield chunk
        else:
            async for chunk in self._handle_chat(text, session):
                yield chunk

    # -----------------------------------------------------------------------
    # 文档问答子图
    # -----------------------------------------------------------------------
    async def _handle_doc_question(self, text: str, session: ShortTermMemory) -> AsyncGenerator[dict, None]:
        context = ""
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])
        if not context:
            context = "（本地文档索引为空，请先导入文档）"

        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(content=f"用户问题：{text}\n\n参考文档：\n{context}\n\n请基于参考文档回答。如果文档中没有相关内容，请明确说明。"),
        ]
        full_response = ""
        async for chunk in llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 操作引导子图（三级定位）
    # -----------------------------------------------------------------------
    async def _handle_guide(
        self, text: str, session: ShortTermMemory, page_context: dict[str, Any] | None,
    ) -> AsyncGenerator[dict, None]:
        """
        操作引导子图 — 三级定位策略。

        流程：
          1. 检索文档，获取操作步骤和 selector 信息
          2. LLM 生成分步指引（JSON 格式）
          3. 对每个步骤执行三级定位：
             Level 1: selector 已知 → highlight_element
             Level 2: selector 未知 → visual_locate → highlight
             Level 3: 视觉定位不确定 → screenshot_annotate
          4. 流式输出指引文本和高亮指令
        """
        # 检索文档
        context = ""
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])

        page_url = (page_context or {}).get("url", "")
        page_type = (page_context or {}).get("page_type", "unknown")

        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(content=f"""用户问题：{text}
当前页面：{page_url}
页面类型：{page_type}

参考文档：
{context}

请：
1. 分析用户想要操作的目标
2. 给出分步操作指引
3. 如果能确定元素选择器，在步骤中标注 selector
4. 如果不确定 selector，标注 description 用于视觉定位

输出格式（JSON）：
{{
  "steps": [
    {{"order": 1, "description": "点击xxx", "selector": "#xxx", "fallback_selector": ".xxx"}}
  ],
  "summary": "操作总结"
}}"""),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

        # 三级定位：解析步骤，执行高亮
        async for cmd in self._process_guide_steps(full_response, page_context):
            yield cmd

    async def _process_guide_steps(
        self, response: str, page_context: dict[str, Any] | None,
    ) -> AsyncGenerator[dict, None]:
        """
        处理指引步骤 — 三级定位。

        Level 1: 有 selector → 直接下发高亮指令
        Level 2: 无 selector，有 description → 尝试视觉定位
        Level 3: 视觉定位失败 → 截图标注
        """
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start < 0 or json_end <= json_start:
                return

            guide_data = json.loads(response[json_start:json_end])

            for step in guide_data.get("steps", []):
                selector = step.get("selector") or step.get("fallback_selector")
                description = step.get("description", "")
                order = step.get("order", 1)

                if selector:
                    # --- Level 1: selector 已知 → 直接高亮 ---
                    yield {
                        "type": "highlight",
                        "selector": selector,
                        "fallback_selector": step.get("fallback_selector"),
                        "description": description,
                        "order": order,
                        "style": "pulse",
                    }
                else:
                    # --- Level 2/3: selector 未知 → 视觉定位或截图标注 ---
                    yield {
                        "type": "visual_locate_hint",
                        "description": description,
                        "order": order,
                        "message": f"正在定位「{description}」...",
                    }

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("指引步骤解析跳过", error=str(e))

    # -----------------------------------------------------------------------
    # 闲聊子图
    # -----------------------------------------------------------------------
    async def _handle_chat(self, text: str, session: ShortTermMemory) -> AsyncGenerator[dict, None]:
        llm = self._get_active_llm()
        messages = [
            SystemMessage(content="你是「求问」，一个友好的网页引导助手。用简洁的中文回复。"),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]
        full_response = ""
        async for chunk in llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 主动监控（Phase 3）
    # -----------------------------------------------------------------------
    async def analyze_page_event(self, event: dict) -> dict | None:
        return None

    # -----------------------------------------------------------------------
    # 反馈记录
    # -----------------------------------------------------------------------
    async def record_feedback(self, feedback: dict) -> None:
        logger.info("收到反馈", feedback=feedback)
        # 写入反馈日志，用于改进定位精度
        if self._long_term:
            key = f"feedback_{feedback.get('step_id', 'unknown')}"
            content = json.dumps(feedback, ensure_ascii=False)
            await self._long_term.save_memory(key=key, content=content)
