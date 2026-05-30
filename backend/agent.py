"""
求问 — LangGraph Agent 引擎
============================

核心职责：
  - 意图分类：doc_question / guide_request / chat
  - 路由分发：根据意图选择不同的处理子图
  - 工具调用：search_docs / fetch_doc_page / save_memory / recall_memory
  - 流式输出：AsyncGenerator yield 消息到 WebSocket

架构：
  用户提问 → 意图分类 → 路由
    ├─ doc_question → 文档检索子图 → 生成回答
    ├─ guide_request → 操作引导子图 → 分步指引 + 高亮指令
    └─ chat → 闲聊子图 → 直接 LLM 回复

模型降级策略（三层）：
  Layer 1: 本地 qwen2.5:7b（默认，零成本）
  Layer 2: 本地 qwen2.5:14b（用户手动切换）
  Layer 3: 云端 GPT-4o-mini（连续失败 ≥ fallback_threshold 次后自动切换）

工具调用流程：
  LLM 返回 tool_calls → 查找工具实例 → 执行 → 将结果作为 ToolMessage 返回 LLM
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
- save_memory: 保存重要信息到长期记忆
- recall_memory: 从长期记忆中搜索信息

回答规则：
1. 先用 search_docs 检索本地文档，有结果就基于结果回答
2. 没有结果时，明确告知用户"本地文档未找到答案"，建议导入文档
3. 操作步骤要具体（点击哪个按钮、在什么位置）
4. 如果能确定元素选择器，在步骤中提供 selector 字段
"""

# 意图分类提示词（独立于主提示词，避免干扰工具调用）
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

    生命周期：
      initialize() → stream_reply() × N → shutdown()

    线程安全：
      Agent 是单例，但 stream_reply 是无状态的（session 由调用方传入），
      多个 WS 连接可以并发调用。
    """

    def __init__(self):
        self._llm: ChatOpenAI | None = None           # 本地 LLM
        self._cloud_llm: ChatOpenAI | None = None     # 云端 LLM（降级用）
        self._long_term: LongTermMemory | None = None  # Chroma 向量库
        self._tools: dict[str, Any] = {}               # 工具名 → 工具实例
        self._consecutive_failures: int = 0            # 连续工具调用失败计数

    # -----------------------------------------------------------------------
    # 初始化 / 销毁
    # -----------------------------------------------------------------------
    async def initialize(self) -> None:
        """
        初始化 Agent。

        步骤：
          1. 创建本地 LLM 客户端（Ollama OpenAI 兼容接口）
          2. 如果配置了云端 API Key，创建云端 LLM 客户端
          3. 初始化 Chroma 向量库连接
          4. 注册所有工具实例
        """
        # 本地 LLM
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",          # Ollama 不需要真实 key
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )

        # 云端 LLM（可选）
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
            logger.info("云端 LLM 已配置", model=settings.cloud_model)

        # Chroma 向量库
        self._long_term = LongTermMemory()
        await self._long_term.initialize()

        # 注册工具
        for tool in get_all_tools():
            self._tools[tool.name] = tool

        logger.info(
            "Agent 初始化完成",
            model=settings.ollama_model,
            strategy=settings.model_strategy.value,
            tools=list(self._tools.keys()),
        )

    async def shutdown(self) -> None:
        """释放资源。"""
        if self._long_term:
            await self._long_term.close()
        self._tools.clear()
        logger.info("Agent 已关闭")

    async def reload_model(self) -> None:
        """
        运行时重新加载模型（热切换）。

        用途：用户在设置面板切换模型后调用，无需重启服务。
        """
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            streaming=True,
            temperature=0.7,
        )
        self._consecutive_failures = 0
        logger.info("模型已切换", model=settings.ollama_model)

    # -----------------------------------------------------------------------
    # 模型选择（降级策略）
    # -----------------------------------------------------------------------
    def _get_active_llm(self) -> ChatOpenAI:
        """
        根据策略和失败计数返回当前应使用的 LLM。

        降级逻辑：
          HYBRID 模式 + 连续失败 ≥ fallback_threshold → 云端
          CLOUD 模式 → 云端
          其他 → 本地
        """
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

    # -----------------------------------------------------------------------
    # 意图分类
    # -----------------------------------------------------------------------
    async def classify_intent(self, question: str) -> str:
        """
        意图分类：doc_question / guide_request / chat。

        使用独立的轻量 LLM 调用，避免干扰主对话的工具调用。

        Returns:
            "doc_question" | "guide_request" | "chat"
        """
        llm = self._get_active_llm()
        prompt = INTENT_CLASSIFY_PROMPT.format(question=question)
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        intent = resp.content.strip().lower()

        # 容错：如果 LLM 返回了非预期的类别，默认为 doc_question
        valid_intents = ("doc_question", "guide_request", "chat")
        if intent not in valid_intents:
            logger.warning("意图分类异常，使用默认值", raw=intent)
            intent = "doc_question"

        logger.info("意图分类完成", question=question[:30], intent=intent)
        return intent

    # -----------------------------------------------------------------------
    # 流式回复（主入口）
    # -----------------------------------------------------------------------
    async def stream_reply(
        self,
        text: str,
        session: ShortTermMemory,
        page_context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        流式生成回复。

        这是 WebSocket 消息处理的主入口。
        通过 yield 多个消息块，实现实时流式输出到前端。

        Args:
            text: 用户输入文本
            session: 当前会话的短期记忆
            page_context: 页面上下文（URL、标题、页面类型等）

        Yields:
            {"type": "agent_thinking", ...}    正在思考
            {"type": "intent_classified", ...} 意图分类结果
            {"type": "agent_token", ...}       流式 token
            {"type": "agent_response", ...}    完整回复
            {"type": "highlight", ...}         高亮指令（guide_request 时）
        """
        yield {"type": "agent_thinking", "text": "正在思考..."}

        # 1. 意图分类
        intent = await self.classify_intent(text)
        yield {"type": "intent_classified", "intent": intent}

        # 2. 根据意图路由到不同处理子图
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
    async def _handle_doc_question(
        self, text: str, session: ShortTermMemory
    ) -> AsyncGenerator[dict, None]:
        """
        处理文档类问题。

        流程：
          1. 从 Chroma 检索相关文档片段
          2. 将检索结果作为上下文注入 prompt
          3. LLM 基于上下文生成回答
          4. 流式 yield token
        """
        # 检索本地文档
        context = ""
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])

        if not context:
            context = "（本地文档索引为空，请先导入文档）"

        # 构建消息列表
        llm = self._get_active_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.to_langchain_messages(),
            HumanMessage(
                content=f"用户问题：{text}\n\n参考文档：\n{context}\n\n"
                "请基于参考文档回答。如果文档中没有相关内容，请明确说明。"
            ),
        ]

        # 流式生成
        full_response = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_response += token
            yield {"type": "agent_token", "token": token}

        # 保存到对话历史
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

    # -----------------------------------------------------------------------
    # 操作引导子图
    # -----------------------------------------------------------------------
    async def _handle_guide(
        self,
        text: str,
        session: ShortTermMemory,
        page_context: dict[str, Any] | None,
    ) -> AsyncGenerator[dict, None]:
        """
        处理操作引导类问题。

        流程：
          1. 检索文档
          2. 构建引导 prompt（要求 LLM 输出 JSON 格式的步骤）
          3. LLM 生成分步指引
          4. 解析 JSON，对有 selector 的步骤下发高亮指令

        高亮指令格式：
          {"type": "highlight", "selector": "#btn", "order": 1, "description": "点击这里"}
        """
        # 检索文档
        context = ""
        if self._long_term:
            docs = await self._long_term.search(text, collection="docs", top_k=5)
            context = "\n---\n".join([d.get("text", "") for d in docs])

        page_url = (page_context or {}).get("url", "")
        page_type = (page_context or {}).get("page_type", "unknown")

        # 构建引导 prompt
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

        # 流式生成
        full_response = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_response += token
            yield {"type": "agent_token", "token": token}

        # 保存到对话历史
        session.add("assistant", full_response)
        yield {"type": "agent_response", "text": full_response}

        # 解析 JSON，下发高亮指令
        yield from self._extract_highlight_commands(full_response)

    def _extract_highlight_commands(self, response: str) -> AsyncGenerator[dict, None]:
        """
        从 LLM 回复中提取高亮指令。

        解析回复中的 JSON 块，对包含 selector 的步骤生成 highlight 消息。
        """
        try:
            # 找到 JSON 块（支持被 ```json 包裹的情况）
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
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
                        }
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("高亮指令解析跳过（非 JSON 格式回复）", error=str(e))

    # -----------------------------------------------------------------------
    # 闲聊子图
    # -----------------------------------------------------------------------
    async def _handle_chat(
        self, text: str, session: ShortTermMemory
    ) -> AsyncGenerator[dict, None]:
        """
        处理闲聊类问题。

        直接用 LLM 回复，不调用工具。
        """
        llm = self._get_active_llm()
        messages = [
            SystemMessage(
                content="你是「求问」，一个友好的网页引导助手。用简洁的中文回复。"
            ),
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

    # -----------------------------------------------------------------------
    # 主动监控（Phase 3 实现）
    # -----------------------------------------------------------------------
    async def analyze_page_event(self, event: dict) -> dict | None:
        """
        分析页面事件，判断是否需要主动介入。

        Phase 3 实现：
          - 检测到表单页面 → 提示用户需要填写
          - 检测到错误页面 → 提供解决方案
          - 检测到用户反复点击同一元素 → 主动询问是否需要帮助
        """
        return None

    # -----------------------------------------------------------------------
    # 反馈记录（Phase 2 实现）
    # -----------------------------------------------------------------------
    async def record_feedback(self, feedback: dict) -> None:
        """
        记录用户反馈。

        Phase 2 实现：
          - "指对了" → 记入成功日志
          - "指错了" → 记入失败日志，累计 ≥ 3 次标记需人工确认
        """
        logger.info("收到反馈", feedback=feedback)
