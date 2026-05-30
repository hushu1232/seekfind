"""
求问 — FastAPI 主入口
=====================

端点清单：
  GET  /health              健康检查
  GET  /api/config          返回当前配置（脱敏）
  POST /api/config/model    运行时切换模型
  POST /api/index/url       从 URL 爬取并构建索引
  POST /api/index/text      从文本构建索引
  GET  /api/index/status    索引状态
  WS   /ws/chat             WebSocket 聊天通道
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
from indexer.build_index import IndexBuilder
from indexer.crawler import CrawledDoc

logger = structlog.get_logger()

active_sessions: dict[str, ShortTermMemory] = {}
agent: QiuWenAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
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
# 健康检查
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------
@app.get("/api/config")
async def get_config():
    return {
        "model_strategy": settings.model_strategy.value,
        "ollama_model": settings.ollama_model,
        "cloud_model": settings.cloud_model if settings.cloud_api_key else None,
        "fallback_threshold": settings.fallback_threshold,
    }


@app.post("/api/config/model")
async def update_model_config(body: dict):
    global agent
    if "model_strategy" in body:
        settings.model_strategy = body["model_strategy"]
    if "ollama_model" in body:
        settings.ollama_model = body["ollama_model"]
    if agent:
        await agent.reload_model()
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


# ---------------------------------------------------------------------------
# 文档索引 API
# ---------------------------------------------------------------------------
@app.post("/api/index/url")
async def index_from_url(body: dict):
    """从 URL 爬取并构建索引。"""
    url = body.get("url", "")
    if not url:
        return JSONResponse(status_code=400, content={"error": "请提供 URL"})

    builder = IndexBuilder()
    try:
        count = await builder.build_from_url(url, agent._long_term)
        return {"status": "ok", "chunks": count}
    except Exception as e:
        logger.error("URL 索引构建失败", url=url, error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/index/text")
async def index_from_text(body: dict):
    """从文本构建索引。"""
    text = body.get("text", "")
    title = body.get("title", "用户导入")
    if not text:
        return JSONResponse(status_code=400, content={"error": "请提供文本"})

    builder = IndexBuilder()
    doc = CrawledDoc(url=f"user://{title}", title=title, text=text)
    try:
        count = await builder.build_from_docs([doc], agent._long_term)
        return {"status": "ok", "chunks": count}
    except Exception as e:
        logger.error("文本索引构建失败", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/index/status")
async def index_status():
    """返回索引状态。"""
    if not agent or not agent._long_term:
        return {"status": "not_ready", "doc_count": 0}
    try:
        count = await agent._long_term.get_collection_count("docs")
        return {"status": "ok", "doc_count": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
        await ws.send_json({"type": "session_created", "session_id": session_id})

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
                async for chunk in agent.stream_reply(text=text, session=session, page_context=page_context):
                    await ws.send_json(chunk)

            elif msg_type == "page_event":
                event_data = msg.get("event", {})
                proactive = await agent.analyze_page_event(event_data)
                if proactive:
                    await ws.send_json(proactive)

            elif msg_type == "feedback":
                await agent.record_feedback(msg.get("feedback", {}))

            elif msg_type == "audio":
                # 语音数据 → ASR → 文本 → Agent
                from voice.asr import asr_service
                audio_base64 = msg.get("audio", "")
                asr_result = await asr_service.process_audio(audio_base64)

                if asr_result["is_wakeword"]:
                    await ws.send_json({"type": "wakeword_detected"})
                elif asr_result["is_command"]:
                    await ws.send_json({"type": "command_detected", "command": "silence"})
                elif asr_result["text"]:
                    # 将识别的文本当作用户消息处理
                    session.add("user", asr_result["text"])
                    async for chunk in agent.stream_reply(text=asr_result["text"], session=session):
                        await ws.send_json(chunk)

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
    uvicorn.run("app:app", host="0.0.0.0", port=settings.bff_port, reload=True)
