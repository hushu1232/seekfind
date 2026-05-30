"""
求问 — LangGraph Agent 引擎
============================

核心架构：
  用户提问 → 意图分类 → 路由到子图
    ├─ doc_question → RAG 子图 (search_docs → LLM → 回复)
    ├─ guide_request → 引导子图 (search_docs → highlight_element → 回复)
    └─ chat → 闲聊子图 (LLM 直接回复)

LangGraph 编排：
  每个子图都是一个 StateGraph：
    agent_node (LLM) → should_continue? → tool_node (执行工具) → agent_node

工具依赖注入：
  long_term_memory 通过 functools.partial 预绑定到工具的 execute 方法。
  ToolNode 调用时只传 LLM 提供的 kwargs，依赖已预绑定。

模型降级：
  _consecutive_failures 在工具调用失败时递增，
  达到 fallback_threshold 后切换到云端模型。
"""

import json
from typing import Any, AsyncGenerator, Annotated, Sequence
from typing_extensions import TypedDict

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import settings, ModelStrategy
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from memory.fingerprint_storage import get_fingerprint_storage
from browser.controller import browser_controller
from tools import get_langchain_tools

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------
SYSTEM_PROMPTS = {
    "doc": """你是「求问」，一个本地智能网页引导助手。

回答文档/知识类问题的规则：
1. 必须先调用 search_docs 工具检索本地文档
2. 如果检索结果不够详细，调用 fetch_doc_page 获取完整页面
3. 基于检索结果回答，引用来源
4. 如果本地文档没有答案，明确告知用户并建议导入文档
5. 用简洁的中文回答，步骤用数字列表
""",
    "guide": """你是「求问」，一个本地智能网页引导助手。

处理操作引导类问题的规则：
1. 必须先调用 search_docs 工具检索相关操作文档
2. 根据文档内容，给出分步操作指引
3. 对于每个步骤，调用 highlight_element 工具在页面上高亮对应元素
4. 如果不确定元素位置，调用 visual_locate 视觉定位
5. 每个步骤的描述要具体（点击哪个按钮、在什么位置）
""",
    "chat": "你是「求问」，一个友好的网页引导助手。用简洁的中文回复闲聊。不需要调用任何工具。",
}

INTENT_CLASSIFY_PROMPT = """判断用户问题的意图类型，只回复一个词：
- doc_question: 关于文档/知识的问题
- guide_request: 需要在页面上引导操作
- chat: 闲聊/其他

用户问题：{question}
意图类型："""


# ---------------------------------------------------------------------------
# State 定义
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# 子图工厂（消除重复）
# ---------------------------------------------------------------------------
def _build_graph(llm_with_tools, system_prompt: str):
    """
    构建 LangGraph StateGraph（通用工厂函数）。

    RAG 和 引导子图结构完全相同，只有系统提示词不同。
    """
    async def agent_node(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode.__new__(ToolNode))  # 占位，实际在 initialize 中设置
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


def _build_graph_real(llm_with_tools, tool_node):
    """构建真实的 StateGraph（带正确的 ToolNode）。"""
    async def agent_node(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ---------------------------------------------------------------------------
# Agent 主类
# ---------------------------------------------------------------------------
class QiuWenAgent:
    """求问 Agent 主类。"""

    def __init__(self):
        self._rag_graph = None
        self._guide_graph = None
        self._chat_llm = None
        self._cloud_llm = None
        self._long_term: LongTermMemory | None = None
        self._fingerprint_storage = None
        self._vision_model = None
        self._consecutive_failures: int = 0

    async def initialize(self) -> None:
        """初始化 LLM、工具（带依赖注入）、LangGraph 子图。"""
        # 本地 LLM
        base_llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )

        # Chroma
        self._long_term = LongTermMemory()
        await self._long_term.initialize()

        # 元素指纹存储（SQLite）
        self._fingerprint_storage = get_fingerprint_storage()

        # 视觉模型（可选，不阻塞启动）
        try:
            from vision.moondream import MoondreamVision
            self._vision_model = MoondreamVision()
            await self._vision_model.initialize()
        except Exception as e:
            logger.warning("视觉模型初始化失败，视觉定位不可用", error=str(e))
            self._vision_model = None

        # 工具（带依赖注入：long_term_memory / fingerprint_storage / vision_model / browser_controller 通过 partial 预绑定）
        langchain_tools = get_langchain_tools(
            long_term_memory=self._long_term,
            fingerprint_storage=self._fingerprint_storage,
            vision_model=self._vision_model,
            browser_controller=browser_controller,
        )
        llm_with_tools = base_llm.bind_tools(langchain_tools)

        # 构建子图
        self._rag_graph = _build_graph_real(llm_with_tools, ToolNode(langchain_tools))
        self._guide_graph = _build_graph_real(llm_with_tools, ToolNode(langchain_tools))
        self._chat_llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )

        # 云端 LLM（可选）
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

        logger.info("Agent 初始化完成", model=settings.ollama_model, tools=len(langchain_tools))

    async def shutdown(self) -> None:
        if self._long_term:
            await self._long_term.close()

    async def reload_model(self) -> None:
        """热切换模型。"""
        base_llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        langchain_tools = get_langchain_tools(
            long_term_memory=self._long_term,
            fingerprint_storage=self._fingerprint_storage,
            vision_model=self._vision_model,
            browser_controller=browser_controller,
        )
        llm_with_tools = base_llm.bind_tools(langchain_tools)
        self._rag_graph = _build_graph_real(llm_with_tools, ToolNode(langchain_tools))
        self._guide_graph = _build_graph_real(llm_with_tools, ToolNode(langchain_tools))
        self._chat_llm = base_llm
        self._consecutive_failures = 0
        logger.info("模型已切换", model=settings.ollama_model)

    # -----------------------------------------------------------------------
    # 模型选择（降级策略）
    # -----------------------------------------------------------------------
    def _get_active_llm(self) -> ChatOpenAI:
        """根据策略和失败计数返回当前 LLM。"""
        if (
            settings.model_strategy == ModelStrategy.HYBRID
            and self._consecutive_failures >= settings.fallback_threshold
            and self._cloud_llm
        ):
            logger.warning("连续失败触发降级", failures=self._consecutive_failures)
            return self._cloud_llm
        if settings.model_strategy == ModelStrategy.CLOUD and self._cloud_llm:
            return self._cloud_llm
        return self._chat_llm

    def _record_tool_failure(self):
        """记录工具调用失败。"""
        self._consecutive_failures += 1
        logger.debug("工具调用失败", failures=self._consecutive_failures)

    def _record_tool_success(self):
        """记录工具调用成功，重置失败计数。"""
        if self._consecutive_failures > 0:
            self._consecutive_failures = 0

    # -----------------------------------------------------------------------
    # 意图分类
    # -----------------------------------------------------------------------
    async def classify_intent(self, question: str) -> str:
        llm = self._get_active_llm()
        resp = await llm.ainvoke([HumanMessage(content=INTENT_CLASSIFY_PROMPT.format(question=question))])
        intent = resp.content.strip().lower()
        return intent if intent in ("doc_question", "guide_request", "chat") else "doc_question"

    # -----------------------------------------------------------------------
    # 流式回复（主入口）
    # -----------------------------------------------------------------------
    async def stream_reply(
        self, text: str, session: ShortTermMemory, page_context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict, None]:
        yield {"type": "agent_thinking", "text": "正在思考..."}

        intent = await self.classify_intent(text)
        yield {"type": "intent_classified", "intent": intent}

        page_info = ""
        if page_context:
            page_info = f"\n当前页面：{page_context.get('url', '')} ({page_context.get('page_type', 'unknown')})"

        if intent == "guide_request":
            async for chunk in self._run_graph(self._guide_graph, SYSTEM_PROMPTS["guide"], text, session, page_info):
                yield chunk
        elif intent == "doc_question":
            async for chunk in self._run_graph(self._rag_graph, SYSTEM_PROMPTS["doc"], text, session, page_info):
                yield chunk
        else:
            async for chunk in self._run_chat(text, session):
                yield chunk

    # -----------------------------------------------------------------------
    # 子图执行（统一方法，消除 _run_rag/_run_guide 重复）
    # -----------------------------------------------------------------------
    async def _run_graph(
        self, graph, system_prompt: str, text: str,
        session: ShortTermMemory, page_info: str,
    ) -> AsyncGenerator[dict, None]:
        """执行 LangGraph 子图（RAG / 引导通用）。"""
        context = await self._retrieve_context(text)

        messages = [
            SystemMessage(content=system_prompt + f"\n\n参考文档：\n{context}{page_info}"),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]

        full_response = ""
        has_tool_calls = False

        async for event in graph.astream({"messages": messages}, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "agent":
                    msg = node_output["messages"][-1]
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            has_tool_calls = True
                            for tc in msg.tool_calls:
                                yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                                # 引导子图：highlight 工具同时下发高亮指令
                                if tc["name"] == "highlight_element":
                                    yield {
                                        "type": "highlight",
                                        "selector": tc["args"].get("selector", ""),
                                        "fallback_selector": tc["args"].get("fallback_selector"),
                                        "description": tc["args"].get("description", ""),
                                        "order": tc["args"].get("order", 1),
                                        "style": tc["args"].get("style", "pulse"),
                                    }
                        if msg.content:
                            full_response += msg.content
                            yield {"type": "agent_token", "token": msg.content}
                elif node_name == "tools":
                    for msg in node_output["messages"]:
                        if isinstance(msg, ToolMessage):
                            yield {"type": "tool_result", "tool": msg.name, "result": msg.content[:200]}
                            # 检查工具是否执行成功
                            if "error" in msg.content.lower():
                                self._record_tool_failure()
                            else:
                                self._record_tool_success()

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 闲聊
    # -----------------------------------------------------------------------
    async def _run_chat(self, text: str, session: ShortTermMemory) -> AsyncGenerator[dict, None]:
        messages = [
            SystemMessage(content=SYSTEM_PROMPTS["chat"]),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]
        full_response = ""
        async for chunk in self._chat_llm.astream(messages):
            full_response += chunk.content
            yield {"type": "agent_token", "token": chunk.content}
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 辅助
    # -----------------------------------------------------------------------
    async def _retrieve_context(self, query: str) -> str:
        if not self._long_term:
            return "（本地文档索引为空）"
        docs = await self._long_term.search(query, collection="docs", top_k=5)
        return "\n---\n".join([d.get("text", "") for d in docs]) if docs else "（本地文档索引为空）"

    async def analyze_page_event(self, event: dict) -> dict | None:
        event_type = event.get("event_type", "")
        if event_type == "user_confused":
            return {"type": "proactive_hint", "message": event.get("message", "需要帮助吗？")}
        if event_type == "route_change":
            url = event.get("url", "")
            if any(p in url.lower() for p in ["/form", "/new", "/create", "/edit", "/register"]):
                return {"type": "proactive_hint", "message": "检测到表单页面，需要我帮你填写吗？"}
        return None

    async def record_feedback(self, feedback: dict) -> None:
        logger.info("收到反馈", feedback=feedback)
        if self._long_term:
            key = f"feedback_{feedback.get('step_id', 'unknown')}"
            await self._long_term.save_memory(key=key, content=json.dumps(feedback, ensure_ascii=False))
