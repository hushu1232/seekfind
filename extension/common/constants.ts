/**
 * 求问 — 常量定义
 * 集中管理地址、消息类型、默认值。
 */

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

export const WS_URL = "ws://localhost:8700/ws/chat";
export const API_BASE = "http://localhost:8700";
export const WS_RECONNECT_INTERVAL = 3000; // ms
export const WS_HEARTBEAT_INTERVAL = 30000; // ms

// ---------------------------------------------------------------------------
// Chrome Storage Keys
// ---------------------------------------------------------------------------

export const STORAGE_KEYS = {
  SESSION_ID: "qiuwen_session_id",
  BALL_STATE: "qiuwen_ball_state",
  CHAT_HISTORY: "qiuwen_chat_history",
  SETTINGS: "qiuwen_settings",
  PRIVACY: "qiuwen_privacy",
} as const;

// ---------------------------------------------------------------------------
// 消息类型（内部通信）
// ---------------------------------------------------------------------------

export const INTERNAL_MSG = {
  // Service Worker ↔ Content Script
  HIGHLIGHT: "qiuwen:highlight",
  CLEAR_HIGHLIGHT: "qiuwen:clear_highlight",
  PAGE_READY: "qiuwen:page_ready",
  PAGE_EVENT: "qiuwen:page_event",
  CAPTURE_TAB: "qiuwen:capture_tab",

  // Service Worker ↔ Sidebar
  WS_CONNECTED: "qiuwen:ws_connected",
  WS_DISCONNECTED: "qiuwen:ws_disconnected",
  SEND_MESSAGE: "qiuwen:send_message",
  RECEIVE_MESSAGE: "qiuwen:receive_message",
  UPDATE_BALL_STATE: "qiuwen:update_ball_state",

  // 操作流录制
  FLOW_STEP: "qiuwen:flow_step",
  RECORDED_STEPS: "qiuwen:recorded_steps",
  START_RECORDING: "qiuwen:start_recording",
  STOP_RECORDING: "qiuwen:stop_recording",

  // 浏览器控制（agent-browser 能力）
  SNAPSHOT: "qiuwen:snapshot",
  SNAPSHOT_RESULT: "qiuwen:snapshot_result",
  FIND_ELEMENT: "qiuwen:find_element",
  FIND_RESULT: "qiuwen:find_result",
  EXECUTE_INTERACTION: "qiuwen:execute_interaction",
  INTERACTION_RESULT: "qiuwen:interaction_result",
} as const;

// ---------------------------------------------------------------------------
// 默认值
// ---------------------------------------------------------------------------

export const DEFAULT_SETTINGS = {
  wsUrl: WS_URL,
  modelStrategy: "hybrid" as const,
  autoListen: false,
  showNotifications: true,
};

export const DEFAULT_PRIVACY = {
  sanitizeEnabled: true,
  historyLearningEnabled: false,
  collectInputs: false,
};
