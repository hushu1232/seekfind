"""
求问 — 数据模型定义 (Pydantic)
===============================

职责：
  - 定义所有 WS 消息的 Pydantic model（类型安全 + 自动验证）
  - 定义页面上下文、反馈数据等业务模型
  - 替代之前的 dict[str, Any] 类型

用法：
  from schemas import UserMessage, PageContext, FeedbackData
  msg = UserMessage(text="怎么创建项目", page_context=PageContext(url="..."))
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class IntentType(str, Enum):
    """意图分类结果。"""
    DOC_QUESTION = "doc_question"
    GUIDE_REQUEST = "guide_request"
    CHAT = "chat"


class BallState(str, Enum):
    """球体状态。"""
    IDLE = "idle"
    THINKING = "thinking"
    SPEAKING = "speaking"
    LISTENING = "listening"
    WATCHING = "watching"
    SLEEPING = "sleeping"


class PageEventType(str, Enum):
    """页面事件类型。"""
    CLICK = "click"
    INPUT = "input"
    SCROLL = "scroll"
    ROUTE_CHANGE = "route_change"
    DOM_CHANGE = "dom_change"


# ---------------------------------------------------------------------------
# 客户端 → 服务端 消息
# ---------------------------------------------------------------------------

class PageContext(BaseModel):
    """页面上下文。"""
    url: str = ""
    title: str = ""
    page_type: str = "unknown"


class UserMessage(BaseModel):
    """用户消息。"""
    type: str = "user_message"
    text: str = Field(..., min_length=1, max_length=5000)
    page_context: Optional[PageContext] = None


class PageEvent(BaseModel):
    """页面事件。"""
    event_type: PageEventType
    timestamp: int = 0
    target: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None


class PageEventMessage(BaseModel):
    """页面事件消息。"""
    type: str = "page_event"
    event: PageEvent


class FeedbackData(BaseModel):
    """反馈数据。"""
    step_id: str
    is_correct: bool
    comment: Optional[str] = None


class FeedbackMessage(BaseModel):
    """反馈消息。"""
    type: str = "feedback"
    feedback: FeedbackData


class AudioMessage(BaseModel):
    """语音消息。"""
    type: str = "audio"
    audio: str = Field(..., description="base64 编码的 PCM 音频")


class PingMessage(BaseModel):
    """心跳消息。"""
    type: str = "ping"


# 客户端消息联合类型
ClientMessage = UserMessage | PageEventMessage | FeedbackMessage | AudioMessage | PingMessage


# ---------------------------------------------------------------------------
# 服务端 → 客户端 消息
# ---------------------------------------------------------------------------

class SessionCreated(BaseModel):
    """会话创建确认。"""
    type: str = "session_created"
    session_id: str


class AgentThinking(BaseModel):
    """Agent 思考中。"""
    type: str = "agent_thinking"
    text: str = "正在思考..."


class IntentClassified(BaseModel):
    """意图分类结果。"""
    type: str = "intent_classified"
    intent: IntentType


class AgentToken(BaseModel):
    """流式 token。"""
    type: str = "agent_token"
    token: str


class AgentResponse(BaseModel):
    """Agent 完整回复。"""
    type: str = "agent_response"
    text: str


class HighlightCommand(BaseModel):
    """高亮指令。"""
    type: str = "highlight"
    selector: str
    fallback_selector: Optional[str] = None
    description: str = ""
    order: int = 1
    style: str = "pulse"  # pulse / glow / arrow


class ToolCallEvent(BaseModel):
    """工具调用事件。"""
    type: str = "tool_call"
    tool: str
    args: dict = {}


class ToolResultEvent(BaseModel):
    """工具执行结果。"""
    type: str = "tool_result"
    tool: str
    result: str


class ScreenshotAnnotated(BaseModel):
    """截图标注结果。"""
    type: str = "screenshot_annotated"
    image_base64: str
    description: Optional[str] = None


class ProactiveHint(BaseModel):
    """主动提示。"""
    type: str = "proactive_hint"
    message: str


class WakewordDetected(BaseModel):
    """唤醒词检测。"""
    type: str = "wakeword_detected"


class CommandDetected(BaseModel):
    """语音指令检测。"""
    type: str = "command_detected"
    command: str


class PongMessage(BaseModel):
    """心跳响应。"""
    type: str = "pong"


# 服务端消息联合类型
ServerMessage = (
    SessionCreated | AgentThinking | IntentClassified | AgentToken |
    AgentResponse | HighlightCommand | ToolCallEvent | ToolResultEvent |
    ScreenshotAnnotated | ProactiveHint | WakewordDetected | CommandDetected |
    PongMessage
)


# ---------------------------------------------------------------------------
# API 请求/响应
# ---------------------------------------------------------------------------

class ModelConfigUpdate(BaseModel):
    """模型配置更新请求。"""
    model_strategy: Optional[str] = None
    ollama_model: Optional[str] = None


class IndexUrlRequest(BaseModel):
    """URL 索引请求。"""
    url: str = Field(..., min_length=1)


class IndexTextRequest(BaseModel):
    """文本索引请求。"""
    text: str = Field(..., min_length=1)
    title: str = "用户导入"


class IndexStatusResponse(BaseModel):
    """索引状态响应。"""
    status: str
    doc_count: int = 0
    error: Optional[str] = None
