"""
求问 — FastAPI 主入口
=====================

端点清单：
  GET  /health          健康检查（Docker healthcheck / 前端连接检测）
  GET  /api/config      返回当前配置（脱敏）
  POST /api/config/model  运行时切换模型（不重启服务）
  WS   /ws/chat         WebSocket 聊天通道（主业务入口）

生命周期：
  startup → 初始化 Agent（加载 LLM + Chroma）
  shutdown → 释放 Agent 资源

消息协议（WS JSON）：
  客户端 → 服务端：
    {"type": "ping"}
    {"type": "user_message", "text": "怎么创建项目", "page_context": {...}}
    {"type": "page_event", "event": {...}}
    {"type": "feedback", "feedback": {...}}
  服务端 → 客户端：
    {"type": "pong"}
    {"type": "session_created", "session_id": "uuid"}
    {"type": "agent_thinking", "text": "正在思考..."}
    {"type": "agent_token", "token": "你"}
    {"type": "agent_response", "text": "完整回复"}
    {"type": "highlight", "selector": "#btn", "description": "点击这里", "order": 1}
"""

import json
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from config import settings
from agent import QiuWenAgent
from memory.short_term import ShortTermMemory

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
# active_sessions: session_id → ShortTermMemory，用于多标签页独立会话
active_sessions: dict[str, ShortTermMemory] = {}

# agent: 全局 Agent 单例，生命周期与 FastAPI 应用一致
agent: QiuWenAgent | None = None


# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期上下文管理器。

    startup 阶段：
      1. 创建 QiuWenAgent 实例
      2. 初始化 LLM 连接（Ollama / 云端）
      3. 初始化 Chroma 向量库连接
      4. 加载内置常识库索引（如果为空）

    shutdown 阶段：
      1. 关闭 Agent，释放 LLM/Chroma 连接
    """
    global agent
    logger.info("求问后端启动中...", port=settings.bff_port)
    agent = QiuWenAgent()
    await agent.initialize()
    logger.info("求问后端就绪", model=settings.ollama_model)
    yield
    logger.info("求问后端关闭中...")
    await agent.shutdown()
    logger.info("求问后端已关闭")


app = FastAPI(
    title="求问 — 本地智能网页引导球",
    description="本地 AI 驱动的网页操作引导助手后端服务",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """
    健康检查端点。

    用途：
      - Docker healthcheck（docker-compose.yml 中配置）
      - 前端 Service Worker 连接检测
      - install.bat/sh 安装验证

    返回示例：
      {"status": "ok", "model_strategy": "hybrid"}
    """
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


@app.get("/api/config")
async def get_config():
    """
    返回当前配置（脱敏版本，不暴露 API Key）。

    用途：前端设置面板读取当前模型配置。
    """
    return {
        "model_strategy": settings.model_strategy.value,
        "ollama_model": settings.ollama_model,
        "cloud_model": settings.cloud_model if settings.cloud_api_key else None,
        "fallback_threshold": settings.fallback_threshold,
    }


@app.post("/api/config/model")
async def update_model_config(body: dict):
    """
    运行时切换模型配置（不重启服务）。

    请求体示例：
      {"model_strategy": "local", "ollama_model": "qwen2.5:14b"}

    流程：
      1. 更新 settings 字段
      2. 调用 agent.reload_model() 重新初始化 LLM 客户端
      3. 返回新配置
    """
    global agent
    if "model_strategy" in body:
        settings.model_strategy = body["model_strategy"]
    if "ollama_model" in body:
        settings.ollama_model = body["ollama_model"]
    if agent:
        await agent.reload_model()
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


# ---------------------------------------------------------------------------
# WebSocket 聊天通道
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    """
    WebSocket 聊天主通道。

    每个连接分配独立 session_id 和 ShortTermMemory。
    支持多标签页同时连接，各自独立会话。

    消息处理流程：
      user_message → 意图分类 → 路由（文档问答/操作引导/闲聊）→ 流式回复
      page_event   → 主动监控分析（Phase 3）
      feedback     → 记录反馈（Phase 2）
    """
    await ws.accept()
    session_id = str(uuid.uuid4())
    session = ShortTermMemory(max_turns=50)
    active_sessions[session_id] = session
    logger.info("WS 连接建立", session_id=session_id, remote=ws.client)

    try:
        # 发送会话创建确认
        await ws.send_json({
            "type": "session_created",
            "session_id": session_id,
        })

        # 消息循环
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            # --- 心跳 ---
            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            # --- 用户消息 → Agent 处理 ---
            if msg_type == "user_message":
                text = msg.get("text", "")
                page_context = msg.get("page_context", {})
                session.add("user", text)
                logger.info("收到用户消息", session_id=session_id, text_len=len(text))

                # 流式生成回复（yield 多个 chunk 到 WS）
                async for chunk in agent.stream_reply(
                    text=text,
                    session=session,
                    page_context=page_context,
                ):
                    await ws.send_json(chunk)

            # --- 页面事件 → 主动监控（Phase 3）---
            elif msg_type == "page_event":
                event_data = msg.get("event", {})
                proactive = await agent.analyze_page_event(event_data)
                if proactive:
                    await ws.send_json(proactive)

            # --- 用户反馈 → 记录（Phase 2）---
            elif msg_type == "feedback":
                feedback_data = msg.get("feedback", {})
                await agent.record_feedback(feedback_data)

            else:
                logger.warning("未知消息类型", msg_type=msg_type, session_id=session_id)

    except WebSocketDisconnect:
        logger.info("WS 连接断开（客户端主动关闭）", session_id=session_id)
    except json.JSONDecodeError as e:
        logger.error("WS 消息 JSON 解析失败", session_id=session_id, error=str(e))
    except Exception as e:
        logger.error("WS 异常", session_id=session_id, error=str(e), exc_info=True)
    finally:
        # 清理会话资源
        active_sessions.pop(session_id, None)
        logger.info("WS 会话已清理", session_id=session_id)


# ---------------------------------------------------------------------------
# 入口（开发模式）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.bff_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
