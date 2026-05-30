/**
 * 求问 — Service Worker (Manifest V3)
 * ====================================
 *
 * 职责：
 *   1. 消息路由（Sidebar ↔ Content Script ↔ 后端）
 *   2. 球体状态管理
 *   3. 使用 WSManager 和 StateStore（拆分的模块）
 *
 * 消息流向：
 *   Sidebar → Service Worker → WSManager → 后端
 *   后端 → WSManager → Service Worker → Sidebar / Content Script
 */

import { INTERNAL_MSG, STORAGE_KEYS } from "../common/constants";
import type { ServerMessage, ClientMessage, BallState, ChatMessage } from "../common/types";
import { WSManager } from "./ws-manager";
import { StateStore } from "./state-store";

// ---------------------------------------------------------------------------
// 模块实例
// ---------------------------------------------------------------------------
const wsManager = new WSManager();
const store = new StateStore();

let ballState: BallState = "idle";

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------
wsManager.setCallbacks(
  // onStatus
  (connected) => {
    broadcastToSidebar({ type: connected ? INTERNAL_MSG.WS_CONNECTED : INTERNAL_MSG.WS_DISCONNECTED });
  },
  // onMessage
  (msg) => handleServerMessage(msg),
);

// ---------------------------------------------------------------------------
// 服务端消息处理
// ---------------------------------------------------------------------------
function handleServerMessage(msg: ServerMessage): void {
  // 全量转发到 Sidebar
  broadcastToSidebar({ type: INTERNAL_MSG.RECEIVE_MESSAGE, payload: msg });

  switch (msg.type) {
    case "session_created":
      store.setSessionId(msg.session_id);
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
      store.appendChatMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: msg.text,
        timestamp: Date.now(),
      });
      break;
  }
}

// ---------------------------------------------------------------------------
// 球体状态
// ---------------------------------------------------------------------------
function setBallState(state: BallState): void {
  ballState = state;
  store.setBallState(state);
  broadcastToSidebar({ type: INTERNAL_MSG.UPDATE_BALL_STATE, state });
}

// ---------------------------------------------------------------------------
// 消息路由
// ---------------------------------------------------------------------------
function broadcastToSidebar(msg: any): void {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case INTERNAL_MSG.SEND_MESSAGE:
      if (wsManager.connected) {
        const userMsg: ClientMessage = {
          type: "user_message",
          text: msg.text,
          page_context: msg.page_context,
        };
        wsManager.send(userMsg);
        store.appendChatMessage({
          id: crypto.randomUUID(),
          role: "user",
          content: msg.text,
          timestamp: Date.now(),
        });
      }
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.PAGE_READY:
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.PAGE_EVENT:
      if (wsManager.connected) {
        wsManager.send({ type: "page_event", event: msg.event });
      }
      sendResponse({ ok: true });
      break;

    case INTERNAL_MSG.CAPTURE_TAB:
      chrome.tabs.captureVisibleTab({ format: "png" }, (dataUrl) => {
        sendResponse({ image: dataUrl });
      });
      return true;
  }
});

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    console.log("[求问] 扩展已安装");
    store.initializeDefaults();
  }
});

// 启动时恢复状态并连接
(async () => {
  ballState = await store.getBallState();
  wsManager.connect();
})();

export {};
