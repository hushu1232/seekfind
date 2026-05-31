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
  | { type: "feedback"; feedback: FeedbackData }
  | { type: "flow_step"; step: FlowStep }
  | { type: "flow_action"; action: "start_recording" | "stop_recording" | "replay" | "list"; flow_name?: string }
  | { type: "browser_snapshot"; options?: SnapshotOptions }
  | { type: "browser_interact"; ref: string; action: string; value?: string };

/** 服务端 → 客户端 */
export type ServerMessage =
  | { type: "pong" }
  | { type: "session_created"; session_id: string }
  | { type: "agent_thinking"; text: string }
  | { type: "intent_classified"; intent: IntentType }
  | { type: "agent_token"; token: string }
  | { type: "agent_response"; text: string }
  | { type: "highlight"; selector: string; fallback_selector?: string; description: string; order: number; style?: HighlightStyle }
  | { type: "screenshot_annotated"; image_base64: string; description?: string }
  | { type: "visual_locate_hint"; description: string; order: number; message: string }
  | { type: "proactive_hint"; message: string }
  | { type: "snapshot_result"; text: string; refCount: number; url: string; title: string }
  | { type: "interaction_result"; success: boolean; error?: string }
  | { type: "agent_error"; error: string };

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
  | "sleeping"   // 休眠
  | "error";     // 错误

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
// 操作流
// ---------------------------------------------------------------------------

export interface FlowStep {
  action: "click" | "input" | "navigate" | "scroll";
  selector: string;
  description: string;
  value?: string;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// 浏览器控制
// ---------------------------------------------------------------------------

export interface SnapshotOptions {
  interactiveOnly?: boolean;
  selector?: string;
  maxDepth?: number;
}

// ---------------------------------------------------------------------------
// 高亮指令
// ---------------------------------------------------------------------------

/** 高亮样式类型 */
export type HighlightStyle = "pulse" | "glow" | "arrow";

export interface HighlightCommand {
  selector: string;
  fallback_selector?: string;
  description: string;
  order: number;
  style?: HighlightStyle;
  duration?: number;
}
