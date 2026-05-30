"""
求问 — LangGraph Agent 引擎
负责意图分类、路由、工具调用、流式输出。
"""

from typing import Any, AsyncGenerator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
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
1. 回答用户关于网页操作的问题（如"怎么创建项目"）
2. 在页面上高亮具体元素，引导用户操作
3. 用简洁、友好的中文回答

你可以使用以下工具：
- search_docs: 从本地文档索引中检索相关信息
- fetch_doc_page: 获取指定 URL 的页面正文
- highlight_element: 在页面上高亮指定元素
- visual_locate: 通过截图视觉定位页面元素
- screenshot_annotate: 在截图上标注（红圈/箭头）
- save_memory / recall_memory: 长期记忆读写
- classify_page: 判断当前页面类型

当用户问"在哪里/怎么操作"类问题时，优先尝试高亮元素引导。
如果本地文档没有答案，明确告知用户并建议导入相关文档。
"""

INTENT_CLASSIFY_PROMPT = """请判断用户问题的意图类型，只回复以下类别之一：
- doc_question: 关于文档/知识的问题（怎么用、是什么、如何操作）
- guide_request: 需要在页面上引导操作（在哪里、帮我找、怎么点）
- chat: 闲聊/打招呼/其他

用户问题：{question}
意图类型："""


class QiuWenAgent:
    """求问 Agent 主类。"""

    def __init__(self):
        self._llm: ChatOpenAI | None = None
        self._cloud_llm: ChatOpenAI | None = None
        self._long_term: LongTermMemory | None = None
        self._consecutive_failures: int = 0

    async def initialize(self):
        """初始化 LLM 和长期记忆。"""
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        if settings.cloud_api_key and settings.model_strategy in (
            ModelStrategy.HYBRID,
            ModelStrategy.CLOUD,
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
        logger.info("Agent 初始化完成", model=settings.ollama_model)

    async def shutdown(self):
        """释放资源。"""
        if self._long_term:
            await self._long_term.close()
        logger.info("Agent 已关闭")

    async def reload_model(self):
        """运行时重新加载模型（热切换）。"""
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
        """根据策略和失败计数返回当前应使用的 LLM。"""
        if (
            settings.model_strategy == ModelStrategy.HYBRID
            and self._consecutive_failures >= settings.fallback_threshold
            and self._cloud_llm
        ):
            logger.warning(
                "连续失败触发降级，切换云端模型",
                failures=self._consecutive_failures,
                cloud_model=settings.cloud_model,
            )
            return self._cloud_llm
        if settings.model_strategy == ModelStrategy.CLOUD and self._cloud_llm:
            return self._cloud_llm
        return self._llm

    async def classify_intent(self, question: str) -> str:
        """意图分类：doc_question / guide_request / chat。"""
        llm = self._get_active_llm()
        prompt = INTENT_CLASSIFY_PROMPT.format(question=question)
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
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
        """流式生成回复，yield 消息到 WebSocket。"""
        yield {"type": "agent_thinking", "text": "正在思考..."}

        # 1. 意图分类
        intent = await self.classify_intent(text)
        yield {"type": "intent_classified", "intent": intent}

        # 2. 根据意图路由
        if intent == "guide_request":
            async for chunk in self._handle_guide(text, session, page_context):
                yield chunk
        elif intent == "doc_question":
            async for chunk in self._handle_doc_question(text, session):
                yield chunk
        else:
            async for chunk in self._handle_chat(text, session):
                yield chunk

    async def _handle_doc_question(
        self, text: str, session: ShortTermMemory
    ) -> AsyncGenerator[dict, None]:
        """处理文档类问题：检索 → 生成回答。"""
        # 检索本地文档
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])
        else:
            context = ""

        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(
                content=f"用户问题：{text}\n\n参考文档：\n{context}\n\n请基于参考文档回答。如果文档中没有相关内容，请说明。"
            ),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_response += token
            yield {"type": "agent_token", "token": token}

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    async def _handle_guide(
        self,
        text: str,
        session: ShortTermMemory,
        page_context: dict[str, Any] | None,
    ) -> AsyncGenerator[dict, None]:
        """处理操作引导类问题：检索 → 生成步骤 → 下发高亮指令。"""
        # 检索文档
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])
        else:
            context = ""

        page_url = (page_context or {}).get("url", "")
        page_type = (page_context or {}).get("page_type", "unknown")

        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(
                content=f"""用户问题：{text}
当前页面：{page_url}
页面类型：{page_type}

参考文档：
{context}

请：
1. 分析用户想要操作的目标
2. 给出分步操作指引
3. 如果能确定元素选择器，在步骤中标注 selector

输出格式（JSON）：
{{
  "steps": [
    {{"order": 1, "description": "点击xxx", "selector": "#xxx", "fallback_selector": ".xxx"}}
  ],
  "summary": "操作总结"
}}"""
            ),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_response += token
            yield {"type": "agent_token", "token": token}

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

        # 尝试下发高亮指令（解析 JSON）
        try:
            import json
            # 从回复中提取 JSON
            json_start = full_response.find("{")
            json_end = full_response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                guide_data = json.loads(full_response[json_start:json_end])
                for step in guide_data.get("steps", []):
                    if step.get("selector"):
                        yield {
                            "type": "highlight",
                            "selector": step["selector"],
                            "fallback_selector": step.get("fallback_selector"),
                            "description": step.get("description", ""),
                            "order": step.get("order", 1),
                        }
        except (json.JSONDecodeError, KeyError):
            pass

    async def _handle_chat(
        self, text: str, session: ShortTermMemory
    ) -> AsyncGenerator[dict, None]:
        """处理闲聊类问题：直接 LLM 回复。"""
        llm = self._get_active_llm()
        messages = [
            SystemMessage(content="你是「求问」，一个友好的网页引导助手。用简洁的中文回复。"),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_response += token
            yield {"type": "agent_token", "token": token}

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    async def analyze_page_event(self, event: dict) -> dict | None:
        """分析页面事件，判断是否需要主动介入。"""
        # Phase 3 实现：主动监控逻辑
        return None

    async def record_feedback(self, feedback: dict):
        """记录用户反馈（指对了/指错了）。"""
        logger.info("收到反馈", feedback=feedback)
        # Phase 2 实现：写入反馈日志
