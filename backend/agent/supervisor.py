"""
求问 — Supervisor Agent
=======================

轻量级任务拆解器。将用户指令拆解为可并行执行的子任务计划。

职责：
  - 接收用户问题 + 最近对话历史
  - 输出 JSON 任务计划（steps 数组）
  - 解析失败时标记 use_fallback=True

不执行重任务，只做拆解。
"""

import json
import asyncio
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings

logger = structlog.get_logger()

SUPERVISOR_PROMPT = """你是一个任务拆解器。分析用户问题，拆解为可并行执行的子任务。

可用任务类型：
- rag: 文档检索问答（search_docs + fetch_doc_page）
- vision: 视觉定位元素（visual_locate + screenshot）
- flow: 操作流匹配（learn_flow replay）
- highlight: 高亮页面元素（highlight_element）
- chat: 闲聊（不需要工具）

输出严格的 JSON（不要添加任何其他文字）：
{{
  "steps": [
    {{"type": "rag", "params": {{"query": "检索关键词"}}}},
    {{"type": "vision", "params": {{"target": "元素描述"}}}}
  ]
}}

规则：
1. 简单问题只输出 1 个 step
2. 复合指令可以输出多个 step（会并行执行）
3. 闲聊输出 {{"steps": [{{"type": "chat", "params": {{}}}}]}}
4. 如果不确定，输出 {{"steps": [{{"type": "rag", "params": {{"query": "用户原话"}}}}]}}

用户问题：{question}"""


class Supervisor:
    """
    Supervisor Agent。

    使用轻量 LLM 拆解任务。失败时标记 use_fallback。
    """

    def __init__(self):
        self._llm = None

    async def initialize(self) -> None:
        """初始化轻量 LLM。"""
        # 使用同一个 Ollama 模型，但 temperature=0 保证输出稳定
        self._llm = ChatOpenAI(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key or "ollama",
            model=settings.ollama_model,
            streaming=False,
            temperature=0,
        )

    async def plan(self, question: str, history: list[str] | None = None) -> dict:
        """
        拆解用户问题为任务计划。

        Returns:
            {"steps": [...], "use_fallback": False}
            或降级: {"steps": [], "use_fallback": True}
        """
        if not self._llm:
            return {"steps": [], "use_fallback": True}

        # 构建 prompt（包含最近 3 条历史）
        history_text = ""
        if history:
            history_text = "\n最近对话：\n" + "\n".join(history[-3:])

        prompt = SUPERVISOR_PROMPT.format(question=question) + history_text

        try:
            resp = await asyncio.wait_for(
                self._llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=8,  # 8 秒超时
            )

            # 解析 JSON
            text = resp.content.strip()
            # 提取 JSON 部分
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                plan = json.loads(text[json_start:json_end])
                steps = plan.get("steps", [])

                # 验证步骤格式
                valid_steps = []
                for step in steps:
                    if isinstance(step, dict) and "type" in step:
                        valid_steps.append({
                            "type": step["type"],
                            "params": step.get("params", {}),
                            "status": "pending",
                        })

                if valid_steps:
                    logger.info("Supervisor 拆解成功", steps=len(valid_steps))
                    return {"steps": valid_steps, "use_fallback": False}

            # 解析失败，降级
            logger.warning("Supervisor 输出格式错误，降级")
            return {"steps": [], "use_fallback": True}

        except asyncio.TimeoutError:
            logger.warning("Supervisor 超时，降级")
            return {"steps": [], "use_fallback": True}
        except Exception as e:
            logger.warning("Supervisor 异常，降级", error=str(e))
            return {"steps": [], "use_fallback": True}
