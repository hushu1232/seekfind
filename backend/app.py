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
  GET  /metrics             Prometheus 指标
  WS   /ws/chat             WebSocket 聊天通道

消息验证：
  所有 WS 消息使用 schemas.py 中的 Pydantic model 进行类型验证。
"""

import json
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from agent_engine import QiuWenAgent
from browser.controller import browser_controller
from config import settings
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from indexer.build_index import IndexBuilder
from indexer.crawler import CrawledDoc
from memory.short_term import ShortTermMemory
from schemas import (
    AudioMessage,
    FeedbackMessage,
    IndexStatusResponse,
    IndexTextRequest,
    IndexUrlRequest,
    ModelConfigUpdate,
    PageEventMessage,
    UserMessage,
)

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
# Prometheus 指标中间件
# ---------------------------------------------------------------------------
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """记录 HTTP 请求指标"""
    from core.metrics import record_http_request

    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    # 记录指标
    record_http_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration=duration,
    )

    return response


# ---------------------------------------------------------------------------
# 健康检查 + Prometheus 指标
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    from core.metrics import get_metrics_content, get_metrics_content_type
    return Response(
        content=get_metrics_content(),
        media_type=get_metrics_content_type(),
    )


@app.get("/api/status")
async def system_status():
    """系统状态：各模块在线/离线状态。"""
    status = {
        "ollama": False,
        "chroma": False,
        "tts": False,
        "asr": False,
        "vision": False,
        "fingerprint_storage": False,
    }

    # 检测 Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_base_url.replace('/v1', '')}/api/tags")
            status["ollama"] = resp.status_code == 200
    except Exception:
        pass

    # 检测 Chroma
    if agent and agent._long_term:
        status["chroma"] = agent._long_term.is_healthy

    # 检测 TTS
    try:
        from voice.tts import tts_service
        status["tts"] = tts_service._use_edge_tts or tts_service._engine is not None
    except Exception:
        pass

    # 检测 ASR
    try:
        from voice.asr import asr_service
        status["asr"] = asr_service._model is not None
    except Exception:
        pass

    # 检测视觉模型
    if agent and agent._vision_model:
        status["vision"] = True

    # 检测指纹存储
    if agent and agent._fingerprint_storage:
        status["fingerprint_storage"] = True

    return status


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
        "enterprise_configured": bool(settings.enterprise_api_base_url and settings.enterprise_api_key),
    }


@app.post("/api/config/model")
async def update_model_config(body: ModelConfigUpdate):
    global agent
    if body.model_strategy:
        settings.model_strategy = body.model_strategy
    if body.ollama_model:
        settings.ollama_model = body.ollama_model
    if agent:
        await agent.reload_model()
    return {"status": "ok", "model_strategy": settings.model_strategy.value}


# ---------------------------------------------------------------------------
# T4.3: 企业版 API（面向企业员工培训）
# ---------------------------------------------------------------------------
@app.get("/api/enterprise/status")
async def enterprise_status():
    """企业版状态：LLM 来源、降级状态等"""
    try:
        from enterprise import get_enterprise_llm_manager
        manager = get_enterprise_llm_manager()
        return manager.get_status()
    except Exception as e:
        return {
            "current_source": "local",
            "enterprise_configured": False,
            "error": str(e),
        }


@app.post("/api/enterprise/check")
async def enterprise_check():
    """检查企业 API 连通性"""
    if not settings.enterprise_api_base_url or not settings.enterprise_api_key:
        return {"status": "not_configured", "message": "企业 API 未配置"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            # 尝试连接企业 API
            response = await client.get(
                f"{settings.enterprise_api_base_url}/models",
                headers={"Authorization": f"Bearer {settings.enterprise_api_key}"},
            )
            if response.status_code == 200:
                return {"status": "ok", "message": "企业 API 连接正常"}
            else:
                return {"status": "error", "message": f"企业 API 返回 {response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"无法连接企业 API: {str(e)}"}


# ---------------------------------------------------------------------------
# 文档索引 API
# ---------------------------------------------------------------------------
@app.post("/api/index/url")
async def index_from_url(body: IndexUrlRequest):
    builder = IndexBuilder()
    try:
        count = await builder.build_from_url(body.url, agent._long_term)
        return {"status": "ok", "chunks": count}
    except Exception as e:
        logger.error("URL 索引构建失败", url=body.url, error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/index/text")
async def index_from_text(body: IndexTextRequest):
    builder = IndexBuilder()
    doc = CrawledDoc(url=f"user://{body.title}", title=body.title, text=body.text)
    try:
        count = await builder.build_from_docs([doc], agent._long_term)
        return {"status": "ok", "chunks": count}
    except Exception as e:
        logger.error("文本索引构建失败", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/index/status", response_model=IndexStatusResponse)
async def index_status():
    if not agent or not agent._long_term:
        return IndexStatusResponse(status="not_ready", doc_count=0)
    try:
        count = await agent._long_term.get_collection_count("docs")
        return IndexStatusResponse(status="ok", doc_count=count)
    except Exception as e:
        return IndexStatusResponse(status="error", error=str(e))


# ---------------------------------------------------------------------------
# WebSocket 聊天通道
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    """
    WebSocket 聊天主通道。

    消息验证流程：
      1. 接收 JSON 文本
      2. 根据 "type" 字段选择对应的 Pydantic model 验证
      3. 验证失败返回错误消息
      4. 验证成功分发到对应处理逻辑
    """
    await ws.accept()
    session_id = str(uuid.uuid4())
    session = ShortTermMemory(max_turns=50)
    active_sessions[session_id] = session
    logger.info("WS 连接建立", session_id=session_id)

    try:
        await ws.send_json({"type": "session_created", "session_id": session_id})

        # 设置浏览器控制器的 WS 连接
        browser_controller.set_ws(ws)

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "无效的 JSON"})
                continue

            msg_type = msg.get("type", "")

            # --- 浏览器控制响应（优先处理）---
            if msg_type in ("snapshot_result", "interaction_result", "find_result"):
                browser_controller.handle_response(msg)
                continue

            # --- 心跳 ---
            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            # --- 用户消息 ---
            if msg_type == "user_message":
                try:
                    validated = UserMessage(**msg)
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"消息格式错误: {e}"})
                    continue

                session.add("user", validated.text)
                page_context = validated.page_context.model_dump() if validated.page_context else {}
                async for chunk in agent.stream_reply(
                    text=validated.text, session=session, page_context=page_context,
                ):
                    await ws.send_json(chunk)

            # --- 页面事件 ---
            elif msg_type == "page_event":
                try:
                    validated = PageEventMessage(**msg)
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"事件格式错误: {e}"})
                    continue

                proactive = await agent.analyze_page_event(validated.event.model_dump())
                if proactive:
                    await ws.send_json(proactive)

            # --- 反馈 ---
            elif msg_type == "feedback":
                try:
                    validated = FeedbackMessage(**msg)
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"反馈格式错误: {e}"})
                    continue

                await agent.record_feedback(validated.feedback.model_dump())

            # --- 语音 ---
            elif msg_type == "audio":
                try:
                    validated = AudioMessage(**msg)
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"音频格式错误: {e}"})
                    continue

                from voice.asr import asr_service
                asr_result = await asr_service.process_audio(validated.audio)

                if asr_result["is_wakeword"]:
                    await ws.send_json({"type": "wakeword_detected"})
                elif asr_result["is_command"]:
                    await ws.send_json({"type": "command_detected", "command": "silence"})
                elif asr_result["text"]:
                    session.add("user", asr_result["text"])
                    async for chunk in agent.stream_reply(text=asr_result["text"], session=session):
                        await ws.send_json(chunk)

            # --- 操作流：实时步骤上报 ---
            elif msg_type == "flow_step":
                step = msg.get("step", {})
                from tools.learn_flow import learn_flow_tool
                learn_flow_tool.add_step(
                    action=step.get("action", "click"),
                    selector=step.get("selector", ""),
                    description=step.get("description", ""),
                    value=step.get("value", ""),
                )
                logger.debug("操作流步骤已记录", action=step.get("action"), selector=step.get("selector"))

            # --- 操作流：控制指令 ---
            elif msg_type == "flow_action":
                action = msg.get("action", "")
                flow_name = msg.get("flow_name", "")
                from tools.learn_flow import learn_flow_tool

                if action == "start_recording":
                    result = await learn_flow_tool.execute("start_recording", flow_name)
                    await ws.send_json({"type": "flow_status", "result": json.loads(result)})
                elif action == "stop_recording":
                    result = await learn_flow_tool.execute("stop_recording")
                    await ws.send_json({"type": "flow_status", "result": json.loads(result)})
                elif action == "replay":
                    result = await learn_flow_tool.execute("replay", flow_name)
                    data = json.loads(result)
                    # 将回放的 steps 转为高亮指令下发
                    if "flow" in data and "steps" in data["flow"]:
                        for step in data["flow"]["steps"]:
                            await ws.send_json({
                                "type": "highlight",
                                "selector": step.get("selector", ""),
                                "description": step.get("description", ""),
                                "order": step.get("order", 1),
                                "style": "pulse",
                            })
                    await ws.send_json({"type": "flow_status", "result": data})
                elif action == "list":
                    result = await learn_flow_tool.execute("list")
                    await ws.send_json({"type": "flow_status", "result": json.loads(result)})
                else:
                    await ws.send_json({"type": "error", "message": f"未知操作流动作: {action}"})

            else:
                await ws.send_json({"type": "error", "message": f"未知消息类型: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("WS 连接断开", session_id=session_id)
    except Exception as e:
        logger.error("WS 异常", session_id=session_id, error=str(e), exc_info=True)
    finally:
        active_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=settings.bff_port, reload=True)
