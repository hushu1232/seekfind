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

// 当前活跃的高亮指令（用于页面切换后恢复）
let activeHighlights: Array<{
  selector: string;
  fallback_selector?: string;
  description: string;
  order: number;
  style?: string;
}> = [];

// 当前活跃的 tab ID
let activeTabId: number | null = null;

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
      // 保存高亮指令（用于页面切换后恢复）
      activeHighlights.push({
        selector: msg.selector,
        fallback_selector: msg.fallback_selector,
        description: msg.description,
        order: msg.order,
        style: (msg as any).style,
      });

      // 路由到 Content Script
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]?.id) {
          activeTabId = tabs[0].id;
          sendHighlightToTab(tabs[0].id, msg);
        }
      });
      break;

    case "agent_thinking":
      // 新问题开始时清除旧高亮
      clearHighlights();
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
      // 不清除高亮 — 用户可能还需要看指引
      // 高亮会在用户发起新问题时自动替换
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

/** 发送高亮指令到指定 tab */
function sendHighlightToTab(tabId: number, highlight: any): void {
  chrome.tabs.sendMessage(tabId, {
    type: INTERNAL_MSG.HIGHLIGHT,
    payload: {
      selector: highlight.selector,
      fallback_selector: highlight.fallback_selector,
      description: highlight.description,
      order: highlight.order,
      style: highlight.style,
    },
  }).catch(() => {});
}

/** 恢复高亮到新页面 */
function restoreHighlights(tabId: number): void {
  if (activeHighlights.length === 0) return;
  console.log(`[求问] 恢复 ${activeHighlights.length} 个高亮到 tab ${tabId}`);
  for (const h of activeHighlights) {
    sendHighlightToTab(tabId, h);
  }
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

// ---------------------------------------------------------------------------
// 页面切换常驻：监听导航事件，恢复高亮
// ---------------------------------------------------------------------------

// 页面加载完成时恢复高亮
chrome.webNavigation?.onCompleted?.addListener((details) => {
  if (details.frameId !== 0) return; // 只处理主框架
  if (activeHighlights.length > 0) {
    // 延迟一点等待 Content Script 加载
    setTimeout(() => restoreHighlights(details.tabId), 500);
  }
});

// 标签页切换时恢复高亮
chrome.tabs?.onActivated?.addListener((activeInfo) => {
  activeTabId = activeInfo.tabId;
  if (activeHighlights.length > 0) {
    setTimeout(() => restoreHighlights(activeInfo.tabId), 300);
  }
});

// 页面开始导航时清除旧高亮（新页面内容不同）
chrome.webNavigation?.onBeforeNavigate?.addListener((details) => {
  if (details.frameId !== 0) return;
  // 如果是同域导航，保留高亮；跨域则清除
  // 简化处理：保留所有高亮，让 Content Script 自行处理失效的 selector
});

// Agent 回复完成时清除高亮缓存
function clearHighlights(): void {
  activeHighlights = [];
}

export {};
