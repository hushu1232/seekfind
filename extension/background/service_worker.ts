/**
 * 求问 — Service Worker (Manifest V3)
 * ====================================
 *
 * 职责：
 *   1. WebSocket 连接管理（连接 / 断线重连 / 心跳）
 *   2. 消息路由（Sidebar ↔ Content Script ↔ 后端）
 *   3. 状态持久化（Chrome Storage）
 *   4. 球体状态管理
 *
 * 消息流向：
 *   Sidebar → Service Worker → WebSocket → 后端
 *   后端 → WebSocket → Service Worker → Sidebar / Content Script
 *
 * 生命周期：
 *   安装 → 连接 WS → 监听消息 → 断线重连 → 卸载
 */

import {
  WS_URL,
  WS_RECONNECT_INTERVAL,
  WS_HEARTBEAT_INTERVAL,
  STORAGE_KEYS,
  INTERNAL_MSG,
} from "../common/constants";
import type {
  ClientMessage,
  ServerMessage,
  BallState,
  ChatMessage,
} from "../common/types";

// ---------------------------------------------------------------------------
// 状态变量
// ---------------------------------------------------------------------------

/** WebSocket 实例 */
let ws: WebSocket | null = null;

/** 当前会话 ID（后端分配） */
let sessionId: string | null = null;

/** 断线重连定时器 */
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** 心跳定时器 */
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

/** 球体当前状态 */
let ballState: BallState = "idle";

/** 聊天历史（最近 N 条） */
let chatHistory: ChatMessage[] = [];

// ---------------------------------------------------------------------------
// WebSocket 连接管理
// ---------------------------------------------------------------------------

/**
 * 建立 WebSocket 连接。
 *
 * 连接流程：
 *   1. 创建 WebSocket 实例
 *   2. onopen → 通知 Sidebar、启动心跳
 *   3. onmessage → 解析 JSON → 分发处理
 *   4. onclose → 通知 Sidebar、停止心跳、调度重连
 *   5. onerror → 日志记录
 */
function connectWebSocket(): void {
  // 防止重复连接
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[求问] WebSocket 已连接");
    broadcastToSidebar({ type: INTERNAL_MSG.WS_CONNECTED });
    startHeartbeat();
    // 清除重连定时器
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = (event) => {
    try {
      const msg: ServerMessage = JSON.parse(event.data);
      handleServerMessage(msg);
    } catch (e) {
      console.error("[求问] 消息解析失败:", e);
    }
  };

  ws.onclose = () => {
    console.log("[求问] WebSocket 已断开");
    broadcastToSidebar({ type: INTERNAL_MSG.WS_DISCONNECTED });
    stopHeartbeat();
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    console.error("[求问] WebSocket 错误:", err);
  };
}

/**
 * 调度断线重连。
 * 使用 WS_RECONNECT_INTERVAL 作为延迟（默认 3 秒）。
 */
function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWebSocket();
  }, WS_RECONNECT_INTERVAL);
}

/**
 * 启动心跳（每 30 秒发送 ping）。
 * 用途：保持连接活跃，检测断线。
 */
function startHeartbeat(): void {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, WS_HEARTBEAT_INTERVAL);
}

/** 停止心跳。 */
function stopHeartbeat(): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

// ---------------------------------------------------------------------------
// 服务端消息处理
// ---------------------------------------------------------------------------

/**
 * 处理从后端 WebSocket 收到的消息。
 *
 * 处理策略：
 *   1. 转发到 Sidebar（所有消息都转发，让 UI 更新）
 *   2. 根据消息类型执行 Service Worker 侧的逻辑
 */
function handleServerMessage(msg: ServerMessage): void {
  // 全量转发到 Sidebar
  broadcastToSidebar({ type: INTERNAL_MSG.RECEIVE_MESSAGE, payload: msg });

  // Service Worker 侧处理
  switch (msg.type) {
    case "session_created":
      // 保存会话 ID
      sessionId = msg.session_id;
      chrome.storage.local.set({ [STORAGE_KEYS.SESSION_ID]: sessionId });
      break;

    case "highlight":
      // 高亮指令 → 路由到当前活跃标签页的 Content Script
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]?.id) {
          chrome.tabs.sendMessage(tabs[0].id, {
            type: INTERNAL_MSG.HIGHLIGHT,
            payload: {
              selector: msg.selector,
              fallback_selector: msg.fallback_selector,
              description: msg.description,
              order: msg.order,
            },
          });
        }
      });
      break;

    case "agent_thinking":
      // 更新球体状态为"思考中"
      setBallState("thinking");
      break;

    case "agent_response":
      // 恢复球体状态为"空闲"
      setBallState("idle");
      // 保存 assistant 消息到聊天历史
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: msg.text,
        timestamp: Date.now(),
      };
      chatHistory.push(assistantMsg);
      chrome.storage.local.set({ [STORAGE_KEYS.CHAT_HISTORY]: chatHistory });
      break;
  }
}

// ---------------------------------------------------------------------------
// 球体状态管理
// ---------------------------------------------------------------------------

/**
 * 设置球体状态并持久化。
 *
 * 状态流转：
 *   idle ↔ thinking ↔ speaking
 *   idle → listening → idle
 *   idle → watching → idle
 *   idle → sleeping → idle
 */
function setBallState(state: BallState): void {
  ballState = state;
  chrome.storage.local.set({ [STORAGE_KEYS.BALL_STATE]: state });
  broadcastToSidebar({ type: INTERNAL_MSG.UPDATE_BALL_STATE, state });
}

// ---------------------------------------------------------------------------
// 内部消息路由（Sidebar ↔ Content Script）
// ---------------------------------------------------------------------------

/**
 * 向所有 Sidebar 实例广播消息。
 * 使用 chrome.runtime.sendMessage，Sidebar 通过 onMessage 接收。
 */
function broadcastToSidebar(msg: any): void {
  chrome.runtime.sendMessage(msg).catch(() => {
    // Sidebar 未打开时会报错，忽略即可
  });
}

/**
 * 监听来自 Sidebar 和 Content Script 的消息。
 *
 * 消息类型：
 *   SEND_MESSAGE   — Sidebar 发来的用户消息，转发到 WS
 *   PAGE_READY     — Content Script 上报页面就绪
 *   PAGE_EVENT     — Content Script 上报页面事件
 *   CAPTURE_TAB    — Sidebar 请求截图
 */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case INTERNAL_MSG.SEND_MESSAGE:
      // Sidebar 用户消息 → 转发到后端 WS
      if (ws && ws.readyState === WebSocket.OPEN) {
        const userMsg: ClientMessage = {
          type: "user_message",
          text: msg.text,
          page_context: msg.page_context,
        };
        ws.send(JSON.stringify(userMsg));

        // 保存 user 消息到聊天历史
        const chatMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "user",
          content: msg.text,
          timestamp: Date.now(),
        };
        chatHistory.push(chatMsg);
        chrome.storage.local.set({ [STORAGE_KEYS.CHAT_HISTORY]: chatHistory });
      }
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.PAGE_READY:
      // Content Script 页面就绪
      console.log("[求问] 页面就绪:", msg.url);
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.PAGE_EVENT:
      // Content Script 页面事件 → 转发到后端
      if (ws && ws.readyState === WebSocket.OPEN) {
        const eventMsg: ClientMessage = {
          type: "page_event",
          event: msg.event,
        };
        ws.send(JSON.stringify(eventMsg));
      }
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.CAPTURE_TAB:
      // Sidebar 截图请求 → 调用 Chrome API
      chrome.tabs.captureVisibleTab({ format: "png" }, (dataUrl) => {
        sendResponse({ image: dataUrl });
      });
      return true; // 异步响应标记
  }
});

// ---------------------------------------------------------------------------
// 扩展生命周期
// ---------------------------------------------------------------------------

/**
 * 首次安装时初始化默认设置。
 */
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    console.log("[求问] 扩展已安装，初始化默认设置");
    chrome.storage.local.set({
      [STORAGE_KEYS.SETTINGS]: { wsUrl: WS_URL },
      [STORAGE_KEYS.CHAT_HISTORY]: [],
      [STORAGE_KEYS.BALL_STATE]: "idle",
    });
  }
});

/**
 * 启动时恢复状态并连接 WebSocket。
 * Service Worker 被唤醒时执行（包括浏览器启动、扩展更新后首次激活）。
 */
chrome.storage.local.get(
  [STORAGE_KEYS.BALL_STATE, STORAGE_KEYS.CHAT_HISTORY],
  (data) => {
    ballState = data[STORAGE_KEYS.BALL_STATE] || "idle";
    chatHistory = data[STORAGE_KEYS.CHAT_HISTORY] || [];
    connectWebSocket();
  }
);

export {};
