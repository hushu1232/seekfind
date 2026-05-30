"""
求问 — LangGraph Agent 引擎
============================

核心职责：
  - 意图分类：doc_question / guide_request / chat
  - 路由分发：根据意图选择不同的处理子图
  - 工具调用：search_docs / highlight / visual_locate / classify_page / learn_flow
  - 流式输出：AsyncGenerator yield 消息到 WebSocket
  - 主动监控：页面事件分析 → 智能介入

架构：
  用户提问 → 意图分类 → 路由
    ├─ doc_question → 文档检索子图 → 生成回答
    ├─ guide_request → 操作引导子图 → 三级定位 → 分步指引
    └─ chat → 闲聊子图 → 直接 LLM 回复

三级定位策略：
  Level 1: selector 已知 → highlight_element
  Level 2: selector 未知 → visual_locate → highlight
  Level 3: 视觉不确定 → screenshot_annotate
"""

import json
from typing import Any, AsyncGenerator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings, ModelStrategy
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from tools import get_all_tools

logger = structlog.get_logger()


SYSTEM_PROMPT = """你是「求问」，一个本地智能网页引导助手。

你可以使用以下工具：
- search_docs: 从本地文档索引中检索相关信息
- fetch_doc_page: 获取指定 URL 的页面正文
- highlight_element: 在页面上高亮指定元素
- visual_locate: 通过截图视觉定位元素
- screenshot_annotate: 在截图上标注元素
- classify_page: 判断页面类型
- learn_flow: 录制/回放操作流
- save_memory / recall_memory: 长期记忆读写

回答规则：
1. 先用 search_docs 检索本地文档
2. 操作步骤要具体（点击哪个按钮、在什么位置）
3. 如果能确定元素选择器，用 highlight_element 高亮
4. 如果不确定选择器，用 visual_locate 视觉定位
"""

INTENT_CLASSIFY_PROMPT = """判断用户问题的意图类型，只回复一个词：
- doc_question: 文档/知识问题
- guide_request: 需要页面引导操作
- chat: 闲聊/其他

用户问题：{question}
意图类型："""


class QiuWenAgent:
    """求问 Agent 主类。"""

    def __init__(self):
        self._llm: ChatOpenAI | None = None
        self._cloud_llm: ChatOpenAI | None = None
        self._long_term: LongTermMemory | None = None
        self._tools: dict[str, Any] = {}
        self._consecutive_failures: int = 0

    async def initialize(self) -> None:
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        if settings.cloud_api_key and settings.model_strategy in (ModelStrategy.HYBRID, ModelStrategy.CLOUD):
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

    async def reload_model(self) -> None:
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        self._consecutive_failures = 0

    def _get_active_llm(self) -> ChatOpenAI:
        if settings.model_strategy == ModelStrategy.HYBRID and self._consecutive_failures >= settings.fallback_threshold and self._cloud_llm:
            return self._cloud_llm
        if settings.model_strategy == ModelStrategy.CLOUD and self._cloud_llm:
            return self._cloud_llm
        return self._llm

    async def classify_intent(self, question: str) -> str:
        llm = self._get_active_llm()
        resp = await llm.ainvoke([HumanMessage(content=INTENT_CLASSIFY_PROMPT.format(question=question))])
        intent = resp.content.strip().lower()
        return intent if intent in ("doc_question", "guide_request", "chat") else "doc_question"

    async def stream_reply(
        self, text: str, session: ShortTermMemory, page_context: dict[str, Any] | None = None,
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

    async def _handle_doc_question(self, text: str, session: ShortTermMemory) -> AsyncGenerator[dict, None]:
        context = ""
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])
        if not context:
            context = "（本地文档索引为空）"

        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(content=f"用户问题：{text}\n\n参考文档：\n{context}"),
        ]
        full_response = ""
        async for chunk in llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    async def _handle_guide(
        self, text: str, session: ShortTermMemory, page_context: dict[str, Any] | None,
    ) -> AsyncGenerator[dict, None]:
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
当前页面：{page_url} ({page_type})
参考文档：{context}

请给出分步操作指引，输出 JSON：
{{"steps": [{{"order": 1, "description": "点击xxx", "selector": "#xxx"}}], "summary": "总结"}}"""),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

        # 三级定位
        async for cmd in self._process_guide_steps(full_response):
            yield cmd

    async def _process_guide_steps(self, response: str) -> AsyncGenerator[dict, None]:
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start < 0 or json_end <= json_start:
                return
            guide_data = json.loads(response[json_start:json_end])
            for step in guide_data.get("steps", []):
                selector = step.get("selector") or step.get("fallback_selector")
                if selector:
                    yield {
                        "type": "highlight",
                        "selector": selector,
                        "fallback_selector": step.get("fallback_selector"),
                        "description": step.get("description", ""),
                        "order": step.get("order", 1),
                        "style": "pulse",
                    }
                else:
                    yield {
                        "type": "visual_locate_hint",
                        "description": step.get("description", ""),
                        "order": step.get("order", 1),
                        "message": f"正在定位「{step.get('description', '')}」...",
                    }
        except (json.JSONDecodeError, KeyError):
            pass

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

    async def analyze_page_event(self, event: dict) -> dict | None:
        """
        分析页面事件，判断是否需要主动介入。

        触发条件：
          - 检测到表单页面 → 提示用户
          - 用户困惑（连续点击同一元素）→ 主动询问
        """
        event_type = event.get("event_type", "")

        # 困惑检测：连续点击
        if event_type == "user_confused":
            return {
                "type": "proactive_hint",
                "message": event.get("message", "检测到你可能需要帮助，有什么问题吗？"),
            }

        # 表单页面检测
        if event_type == "route_change":
            url = event.get("url", "")
            if any(p in url.lower() for p in ["/form", "/new", "/create", "/edit", "/register"]):
                return {
                    "type": "proactive_hint",
                    "message": "检测到表单页面，需要我帮你填写吗？",
                }

        return None

    async def record_feedback(self, feedback: dict) -> None:
        logger.info("收到反馈", feedback=feedback)
        if self._long_term:
            key = f"feedback_{feedback.get('step_id', 'unknown')}"
            await self._long_term.save_memory(key=key, content=json.dumps(feedback, ensure_ascii=False))
