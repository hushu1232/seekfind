/**
 * 求问 — 共享类型定义
 * 所有模块共享的接口和类型。
 */

// ---------------------------------------------------------------------------
// WebSocket 消息类型
// ---------------------------------------------------------------------------

/** 客户端 → 服务端 */
export type ClientMessage =
  | { type: "ping" }
  | { type: "user_message"; text: string; page_context?: PageContext }
  | { type: "page_event"; event: PageEvent }
  | { type: "feedback"; feedback: FeedbackData };

/** 服务端 → 客户端 */
export type ServerMessage =
  | { type: "pong" }
  | { type: "session_created"; session_id: string }
  | { type: "agent_thinking"; text: string }
  | { type: "intent_classified"; intent: IntentType }
  | { type: "agent_token"; token: string }
  | { type: "agent_response"; text: string }
  | { type: "highlight"; selector: string; fallback_selector?: string; description: string; order: number }
  | { type: "screenshot_annotated"; image_base64: string }
  | { type: "proactive_hint"; message: string };

// ---------------------------------------------------------------------------
// 意图类型
// ---------------------------------------------------------------------------

export type IntentType = "doc_question" | "guide_request" | "chat";

// ---------------------------------------------------------------------------
// 页面上下文
// ---------------------------------------------------------------------------

export interface PageContext {
  url: string;
  title: string;
  page_type?: string;
  dom_snapshot?: string;
}

// ---------------------------------------------------------------------------
// 页面事件
// ---------------------------------------------------------------------------

export interface PageEvent {
  event_type: "click" | "input" | "scroll" | "route_change" | "dom_change";
  timestamp: number;
  target?: string;
  value?: string;
  url?: string;
}

// ---------------------------------------------------------------------------
// 反馈数据
// ---------------------------------------------------------------------------

export interface FeedbackData {
  step_id: string;
  is_correct: boolean;
  comment?: string;
}

// ---------------------------------------------------------------------------
// 球体状态
// ---------------------------------------------------------------------------

export type BallState =
  | "idle"       // 空闲
  | "thinking"   // 思考中
  | "speaking"   // 说话中
  | "listening"  // 监听中
  | "watching"   // 观察中
  | "sleeping";  // 休眠

// ---------------------------------------------------------------------------
// 对话消息
// ---------------------------------------------------------------------------

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  intent?: IntentType;
}

// ---------------------------------------------------------------------------
// 高亮指令
// ---------------------------------------------------------------------------

export interface HighlightCommand {
  selector: string;
  fallback_selector?: string;
  description: string;
  order: number;
  style?: "pulse" | "glow" | "arrow";
  duration?: number;
}
