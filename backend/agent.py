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
    当 LLM 不再返回 tool_calls 时，结束循环。

工具调用流程：
  1. LLM 分析用户问题，返回 tool_calls（如调用 search_docs）
  2. tool_node 查找工具实例，执行，返回 ToolMessage
  3. LLM 收到 ToolMessage，生成最终回复（或继续调用更多工具）
  4. 当 LLM 不再需要工具时，输出最终文本回复
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
from tools import get_all_tools, get_langchain_tools

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_DOC = """你是「求问」，一个本地智能网页引导助手。

回答文档/知识类问题的规则：
1. 必须先调用 search_docs 工具检索本地文档
2. 如果检索结果不够详细，调用 fetch_doc_page 获取完整页面
3. 基于检索结果回答，引用来源
4. 如果本地文档没有答案，明确告知用户并建议导入文档
5. 用简洁的中文回答，步骤用数字列表
"""

SYSTEM_PROMPT_GUIDE = """你是「求问」，一个本地智能网页引导助手。

处理操作引导类问题的规则：
1. 必须先调用 search_docs 工具检索相关操作文档
2. 根据文档内容，给出分步操作指引
3. 对于每个步骤，调用 highlight_element 工具在页面上高亮对应元素
4. 如果不确定元素位置，调用 visual_locate 视觉定位
5. 每个步骤的描述要具体（点击哪个按钮、在什么位置）
"""

SYSTEM_PROMPT_CHAT = """你是「求问」，一个友好的网页引导助手。用简洁的中文回复闲聊。
不需要调用任何工具，直接回复即可。
"""

INTENT_CLASSIFY_PROMPT = """判断用户问题的意图类型，只回复一个词：
- doc_question: 关于文档/知识的问题（怎么用、是什么、如何操作）
- guide_request: 需要在页面上引导操作（在哪里、帮我找、怎么点）
- chat: 闲聊/打招呼/其他

用户问题：{question}
意图类型："""


# ---------------------------------------------------------------------------
# State 定义
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    """LangGraph Agent 状态。"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------
_all_tools = get_all_tools()
_langchain_tools = get_langchain_tools()
_tool_map = {t.name: t for t in _all_tools}


# ---------------------------------------------------------------------------
# 子图构建
# ---------------------------------------------------------------------------
def _build_rag_graph(llm_with_tools: ChatOpenAI):
    """
    构建 RAG（文档问答）子图。

    流程：
      agent_node → should_continue → tool_node → agent_node → ... → END
    """
    async def agent_node(state: AgentState) -> dict:
        """LLM 节点：调用 LLM 生成回复或工具调用。"""
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        """条件路由：LLM 返回 tool_calls 时继续执行工具，否则结束。"""
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    # ToolNode：自动执行 LLM 返回的 tool_calls（需要 LangChain StructuredTool）
    tool_node = ToolNode(_langchain_tools)

    # 构建 StateGraph
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    # 边：agent → should_continue → tools / END
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")  # 工具执行完回到 agent

    return graph.compile()


def _build_guide_graph(llm_with_tools: ChatOpenAI):
    """
    构建操作引导子图。
    与 RAG 子图结构相同，但系统提示词不同（要求调用 highlight_element）。
    """
    async def agent_node(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(_langchain_tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


def _build_chat_llm() -> ChatOpenAI:
    """闲聊不需要工具，直接返回 LLM 实例。"""
    return ChatOpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        model=settings.ollama_model,
        streaming=True,
        temperature=0.7,
    )


# ---------------------------------------------------------------------------
# Agent 主类
# ---------------------------------------------------------------------------
class QiuWenAgent:
    """
    求问 Agent 主类。

    属性：
      _rag_graph: RAG 子图（文档问答）
      _guide_graph: 引导子图（操作引导）
      _chat_llm: 闲聊 LLM（无工具）
      _long_term: Chroma 向量库
      _consecutive_failures: 连续失败计数（降级用）
    """

    def __init__(self):
        self._rag_graph = None
        self._guide_graph = None
        self._chat_llm = None
        self._cloud_llm = None
        self._long_term: LongTermMemory | None = None
        self._consecutive_failures: int = 0

    async def initialize(self) -> None:
        """初始化 LLM、工具绑定、LangGraph 子图。"""
        # 创建 LLM 并绑定工具
        base_llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        llm_with_tools = base_llm.bind_tools(_langchain_tools)

        # 构建子图
        self._rag_graph = _build_rag_graph(llm_with_tools)
        self._guide_graph = _build_guide_graph(llm_with_tools)
        self._chat_llm = _build_chat_llm()

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

        # Chroma
        self._long_term = LongTermMemory()
        await self._long_term.initialize()

        logger.info(
            "Agent 初始化完成",
            model=settings.ollama_model,
            tools=[t.name for t in _all_tools],
        )

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
        llm_with_tools = base_llm.bind_tools(_langchain_tools)
        self._rag_graph = _build_rag_graph(llm_with_tools)
        self._guide_graph = _build_guide_graph(llm_with_tools)
        self._chat_llm = _build_chat_llm()
        self._consecutive_failures = 0
        logger.info("模型已切换", model=settings.ollama_model)

    # -----------------------------------------------------------------------
    # 意图分类
    # -----------------------------------------------------------------------
    async def classify_intent(self, question: str) -> str:
        llm = self._chat_llm
        resp = await llm.ainvoke([HumanMessage(content=INTENT_CLASSIFY_PROMPT.format(question=question))])
        intent = resp.content.strip().lower()
        return intent if intent in ("doc_question", "guide_request", "chat") else "doc_question"

    # -----------------------------------------------------------------------
    # 流式回复（主入口）
    # -----------------------------------------------------------------------
    async def stream_reply(
        self, text: str, session: ShortTermMemory, page_context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        流式生成回复。

        流程：
          1. 意图分类
          2. 构建消息列表（系统提示 + 历史 + 用户消息 + 页面上下文）
          3. 调用对应子图（RAG / 引导 / 闲聊）
          4. 流式 yield 消息到 WS
        """
        yield {"type": "agent_thinking", "text": "正在思考..."}

        # 1. 意图分类
        intent = await self.classify_intent(text)
        yield {"type": "intent_classified", "intent": intent}

        # 2. 构建上下文
        page_info = ""
        if page_context:
            page_info = f"\n当前页面：{page_context.get('url', '')} ({page_context.get('page_type', 'unknown')})"

        # 3. 根据意图路由
        if intent == "guide_request":
            async for chunk in self._run_guide(text, session, page_info):
                yield chunk
        elif intent == "doc_question":
            async for chunk in self._run_rag(text, session, page_info):
                yield chunk
        else:
            async for chunk in self._run_chat(text, session):
                yield chunk

    # -----------------------------------------------------------------------
    # RAG 子图执行
    # -----------------------------------------------------------------------
    async def _run_rag(self, text: str, session: ShortTermMemory, page_info: str) -> AsyncGenerator[dict, None]:
        """执行 RAG 子图：search_docs → LLM → 回复。"""
        # 检索上下文
        context = await self._retrieve_context(text)

        # 构建消息
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_DOC + f"\n\n参考文档：\n{context}{page_info}"),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]

        # 流式执行 LangGraph
        full_response = ""
        async for event in self._rag_graph.astream({"messages": messages}, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "agent":
                    msg = node_output["messages"][-1]
                    if isinstance(msg, AIMessage):
                        # 工具调用消息
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                        # 文本回复
                        if msg.content:
                            token = msg.content
                            full_response += token
                            yield {"type": "agent_token", "token": token}
                elif node_name == "tools":
                    # 工具执行结果
                    for msg in node_output["messages"]:
                        if isinstance(msg, ToolMessage):
                            yield {"type": "tool_result", "tool": msg.name, "result": msg.content[:200]}

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 引导子图执行
    # -----------------------------------------------------------------------
    async def _run_guide(self, text: str, session: ShortTermMemory, page_info: str) -> AsyncGenerator[dict, None]:
        """执行引导子图：search_docs → highlight_element → LLM → 回复。"""
        context = await self._retrieve_context(text)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_GUIDE + f"\n\n参考文档：\n{context}{page_info}"),
            *session.to_langchain_messages(),
            HumanMessage(content=text),
        ]

        full_response = ""
        async for event in self._guide_graph.astream({"messages": messages}, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "agent":
                    msg = node_output["messages"][-1]
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                                # 如果是 highlight 工具，同时下发高亮指令
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

        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 闲聊子图执行
    # -----------------------------------------------------------------------
    async def _run_chat(self, text: str, session: ShortTermMemory) -> AsyncGenerator[dict, None]:
        """闲聊：直接 LLM 回复，不调用工具。"""
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_CHAT),
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
    # 辅助方法
    # -----------------------------------------------------------------------
    async def _retrieve_context(self, query: str) -> str:
        """从 Chroma 检索相关文档作为上下文。"""
        if not self._long_term:
            return "（本地文档索引为空）"
        docs = await self._long_term.search(query, collection="docs", top_k=5)
        if not docs:
            return "（本地文档索引为空）"
        return "\n---\n".join([d.get("text", "") for d in docs])

    async def analyze_page_event(self, event: dict) -> dict | None:
        """分析页面事件，判断是否需要主动介入。"""
        event_type = event.get("event_type", "")
        if event_type == "user_confused":
            return {"type": "proactive_hint", "message": event.get("message", "需要帮助吗？")}
        if event_type == "route_change":
            url = event.get("url", "")
            if any(p in url.lower() for p in ["/form", "/new", "/create", "/edit", "/register"]):
                return {"type": "proactive_hint", "message": "检测到表单页面，需要我帮你填写吗？"}
        return None

    async def record_feedback(self, feedback: dict) -> None:
        """记录用户反馈。"""
        logger.info("收到反馈", feedback=feedback)
        if self._long_term:
            key = f"feedback_{feedback.get('step_id', 'unknown')}"
            await self._long_term.save_memory(key=key, content=json.dumps(feedback, ensure_ascii=False))
