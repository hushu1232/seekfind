"""
求问 — FastAPI 主入口
提供 /health 健康检查和 /ws/chat WebSocket 聊天通道。
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
active_sessions: dict[str, ShortTermMemory] = {}
agent: QiuWenAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭生命周期管理。"""
    global agent
    logger.info("求问后端启动中...", port=settings.bff_port)
    agent = QiuWenAgent()
    await agent.initialize()
    logger.info("求问后端就绪")
    yield
    logger.info("求问后端关闭中...")
    await agent.shutdown()
    logger.info("求问后端已关闭")


app = FastAPI(
    title="求问 — 本地智能网页引导球",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """健康检查。"""
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


@app.get("/api/config")
async def get_config():
    """返回当前配置（脱敏）。"""
    return {
        "model_strategy": settings.model_strategy.value,
        "ollama_model": settings.ollama_model,
        "cloud_model": settings.cloud_model if settings.cloud_api_key else None,
        "fallback_threshold": settings.fallback_threshold,
    }


@app.post("/api/config/model")
async def update_model_config(body: dict):
    """运行时切换模型配置（不重启服务）。"""
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
    await ws.accept()
    session_id = str(uuid.uuid4())
    session = ShortTermMemory(max_turns=50)
    active_sessions[session_id] = session
    logger.info("WS 连接建立", session_id=session_id)

    try:
        # 发送欢迎消息
        await ws.send_json({
            "type": "session_created",
            "session_id": session_id,
        })

        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            if msg_type == "user_message":
                text = msg.get("text", "")
                page_context = msg.get("page_context", {})
                session.add("user", text)

                # 流式生成回复
                async for chunk in agent.stream_reply(
                    text=text,
                    session=session,
                    page_context=page_context,
                ):
                    await ws.send_json(chunk)

            elif msg_type == "page_event":
                # 页面事件（DOM 变化、点击等）→ 主动监控
                event_data = msg.get("event", {})
                proactive = await agent.analyze_page_event(event_data)
                if proactive:
                    await ws.send_json(proactive)

            elif msg_type == "feedback":
                # 用户反馈（指对了/指错了）
                feedback_data = msg.get("feedback", {})
                await agent.record_feedback(feedback_data)

            else:
                logger.warning("未知消息类型", msg_type=msg_type)

    except WebSocketDisconnect:
        logger.info("WS 连接断开", session_id=session_id)
    except Exception as e:
        logger.error("WS 异常", session_id=session_id, error=str(e))
    finally:
        active_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# 入口
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
