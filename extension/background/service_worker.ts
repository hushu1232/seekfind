/**
 * 求问 — Service Worker
 * 负责 WebSocket 连接管理、消息路由、状态持久化。
 */

import { WS_URL, WS_RECONNECT_INTERVAL, WS_HEARTBEAT_INTERVAL, STORAGE_KEYS, INTERNAL_MSG } from "../common/constants";
import type { ClientMessage, ServerMessage, BallState, ChatMessage } from "../common/types";

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
let ws: WebSocket | null = null;
let sessionId: string | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let ballState: BallState = "idle";
let chatHistory: ChatMessage[] = [];

// ---------------------------------------------------------------------------
// WebSocket 连接
// ---------------------------------------------------------------------------
function connectWebSocket(): void {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[求问] WebSocket 已连接");
    broadcastToSidebar({ type: INTERNAL_MSG.WS_CONNECTED });
    startHeartbeat();
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

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWebSocket();
  }, WS_RECONNECT_INTERVAL);
}

function startHeartbeat(): void {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, WS_HEARTBEAT_INTERVAL);
}

function stopHeartbeat(): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

// ---------------------------------------------------------------------------
// 消息处理
// ---------------------------------------------------------------------------
function handleServerMessage(msg: ServerMessage): void {
  // 转发到 Sidebar
  broadcastToSidebar({ type: INTERNAL_MSG.RECEIVE_MESSAGE, payload: msg });

  // 处理需要 Service Worker 执行的指令
  switch (msg.type) {
    case "session_created":
      sessionId = msg.session_id;
      chrome.storage.local.set({ [STORAGE_KEYS.SESSION_ID]: sessionId });
      break;

    case "highlight":
      // 路由到 Content Script
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
      setBallState("thinking");
      break;

    case "agent_response":
      setBallState("idle");
      // 保存到聊天历史
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
function setBallState(state: BallState): void {
  ballState = state;
  chrome.storage.local.set({ [STORAGE_KEYS.BALL_STATE]: state });
  broadcastToSidebar({ type: INTERNAL_MSG.UPDATE_BALL_STATE, state });
}

// ---------------------------------------------------------------------------
// 内部消息路由（Sidebar ↔ Content Script）
// ---------------------------------------------------------------------------
function broadcastToSidebar(msg: any): void {
  // 向所有 sidebar 发送消息
  chrome.runtime.sendMessage(msg).catch(() => {});
}

// 监听来自 Sidebar 和 Content Script 的消息
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case INTERNAL_MSG.SEND_MESSAGE:
      // Sidebar 发来的用户消息 → 转发到 WS
      if (ws && ws.readyState === WebSocket.OPEN) {
        const userMsg: ClientMessage = {
          type: "user_message",
          text: msg.text,
          page_context: msg.page_context,
        };
        ws.send(JSON.stringify(userMsg));

        // 保存到聊天历史
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
      // Content Script 上报页面就绪
      console.log("[求问] 页面就绪:", msg.url);
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.PAGE_EVENT:
      // Content Script 上报页面事件
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
      // Sidebar 请求截图
      chrome.tabs.captureVisibleTab({ format: "png" }, (dataUrl) => {
        sendResponse({ image: dataUrl });
      });
      return true; // 异步响应
  }
});

// ---------------------------------------------------------------------------
// 扩展生命周期
// ---------------------------------------------------------------------------
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    console.log("[求问] 扩展已安装");
    // 初始化默认设置
    chrome.storage.local.set({
      [STORAGE_KEYS.SETTINGS]: { wsUrl: WS_URL },
      [STORAGE_KEYS.CHAT_HISTORY]: [],
    });
  }
});

// 启动时恢复状态并连接
chrome.storage.local.get([STORAGE_KEYS.BALL_STATE, STORAGE_KEYS.CHAT_HISTORY], (data) => {
  ballState = data[STORAGE_KEYS.BALL_STATE] || "idle";
  chatHistory = data[STORAGE_KEYS.CHAT_HISTORY] || [];
  connectWebSocket();
});

export {};
