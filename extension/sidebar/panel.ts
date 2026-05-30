/**
 * 求问 — Sidebar 对话面板
 * =========================
 *
 * 职责：
 *   1. 渲染消息列表（user / assistant 消息）
 *   2. 处理用户输入（发送到 Service Worker）
 *   3. 接收并显示 Agent 的流式回复
 *   4. 显示步骤卡片 + 反馈按钮
 *   5. 恢复聊天历史
 *
 * 消息流向：
 *   用户输入 → chrome.runtime.sendMessage(SEND_MESSAGE) → Service Worker → WS → 后端
 *   后端 → WS → Service Worker → chrome.runtime.onMessage → 本面板渲染
 */

import { INTERNAL_MSG, STORAGE_KEYS } from "../common/constants";
import type { ServerMessage, ChatMessage } from "../common/types";

// ---------------------------------------------------------------------------
// DOM 元素引用
// ---------------------------------------------------------------------------

const messagesEl = document.getElementById("messages")!;
const userInputEl = document.getElementById("user-input") as HTMLInputElement;
const sendBtnEl = document.getElementById("send-btn") as HTMLButtonElement;
const wsStatusEl = document.getElementById("ws-status")!;
const ballContainerEl = document.getElementById("ball-container")!;

/** 是否正在等待 Agent 回复（禁用输入） */
let isProcessing = false;

/** 当前正在流式追加的 assistant 消息元素 */
let currentAssistantEl: HTMLDivElement | null = null;

// ---------------------------------------------------------------------------
// 初始化：恢复聊天历史
// ---------------------------------------------------------------------------

/**
 * 从 Chrome Storage 恢复最近 20 条聊天历史。
 * Service Worker 在启动时已恢复完整历史，这里只取最近的用于显示。
 */
chrome.storage.local.get([STORAGE_KEYS.CHAT_HISTORY], (data) => {
  const history: ChatMessage[] = data[STORAGE_KEYS.CHAT_HISTORY] || [];
  for (const msg of history.slice(-20)) {
    appendMessage(msg.role, msg.content, false);
  }
  scrollToBottom();
});

// ---------------------------------------------------------------------------
// 发送消息
// ---------------------------------------------------------------------------

/**
 * 发送用户消息到 Service Worker。
 *
 * 流程：
 *   1. 获取输入框文本
 *   2. 显示用户消息气泡
 *   3. 清空输入框，禁用发送按钮
 *   4. 通过 chrome.runtime.sendMessage 发送到 Service Worker
 */
function sendMessage(): void {
  const text = userInputEl.value.trim();
  if (!text || isProcessing) return;

  // 显示用户消息
  appendMessage("user", text);
  userInputEl.value = "";

  // 禁用输入（等待 Agent 回复）
  isProcessing = true;
  sendBtnEl.disabled = true;

  // 发送到 Service Worker → WS → 后端
  chrome.runtime.sendMessage({
    type: INTERNAL_MSG.SEND_MESSAGE,
    text,
    page_context: {
      url: window.location.href,
      title: document.title,
    },
  });
}

// 事件绑定
sendBtnEl.addEventListener("click", sendMessage);
userInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// ---------------------------------------------------------------------------
// 接收消息（来自 Service Worker）
// ---------------------------------------------------------------------------

/**
 * 监听 Service Worker 转发的消息。
 *
 * 消息类型：
 *   agent_thinking   → 显示"正在思考..."
 *   agent_token      → 流式追加 token 到当前消息
 *   agent_response   → 完成，启用输入
 *   highlight        → 显示步骤卡片
 *   proactive_hint   → 显示主动提示
 *   WS_CONNECTED     → 更新连接状态指示器
 *   WS_DISCONNECTED  → 更新连接状态指示器
 *   UPDATE_BALL_STATE → 更新球体状态（Phase 3）
 */
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== INTERNAL_MSG.RECEIVE_MESSAGE) return;

  const payload: ServerMessage = msg.payload;

  switch (payload.type) {
    case "agent_thinking":
      // 创建占位消息，显示"正在思考..."
      currentAssistantEl = appendMessage("assistant", "🤔 正在思考...", true);
      break;

    case "agent_token":
      // 流式追加 token
      if (currentAssistantEl) {
        currentAssistantEl.classList.remove("thinking");
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) {
          textNode.textContent += payload.token;
        } else {
          currentAssistantEl.innerHTML = `<span class="message-text">${escapeHtml(payload.token)}</span>`;
        }
        scrollToBottom();
      }
      break;

    case "agent_response":
      // 回复完成
      if (currentAssistantEl) {
        currentAssistantEl.classList.remove("thinking");
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) {
          textNode.textContent = payload.text;
        }
      }
      currentAssistantEl = null;
      isProcessing = false;
      sendBtnEl.disabled = false;
      scrollToBottom();
      break;

    case "highlight":
      // 显示步骤卡片（带反馈按钮）
      appendStepCard(payload.order, payload.description, payload.selector);
      break;

    case "proactive_hint":
      // 主动提示（Phase 3）
      appendMessage("assistant", `💡 ${payload.message}`);
      break;
  }

  // 连接状态更新
  if (msg.type === INTERNAL_MSG.WS_CONNECTED) {
    wsStatusEl.classList.add("connected");
  }
  if (msg.type === INTERNAL_MSG.WS_DISCONNECTED) {
    wsStatusEl.classList.remove("connected");
  }
  if (msg.type === INTERNAL_MSG.UPDATE_BALL_STATE) {
    updateBallState(msg.state);
  }
});

// ---------------------------------------------------------------------------
// UI 辅助函数
// ---------------------------------------------------------------------------

/**
 * 向消息列表追加一条消息。
 *
 * @param role     "user" 或 "assistant"
 * @param content  消息文本
 * @param thinking 是否为"思考中"占位消息
 * @returns 创建的消息 DOM 元素
 */
function appendMessage(
  role: "user" | "assistant",
  content: string,
  thinking = false
): HTMLDivElement {
  const div = document.createElement("div");
  div.className = `message ${role}${thinking ? " thinking" : ""}`;
  div.innerHTML = `<span class="message-text">${escapeHtml(content)}</span>`;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

/**
 * 追加步骤卡片（带反馈按钮）。
 *
 * 卡片结构：
 *   <div class="step-card">
 *     <div class="step-header">第 N 步</div>
 *     <div class="step-desc">描述</div>
 *     <div class="feedback-btns">
 *       <button class="btn-correct">✅ 指对了</button>
 *       <button class="btn-wrong">❌ 指错了</button>
 *     </div>
 *   </div>
 */
function appendStepCard(order: number, description: string, selector: string): void {
  const card = document.createElement("div");
  card.className = "step-card";
  card.innerHTML = `
    <div class="step-header">第 ${order} 步</div>
    <div class="step-desc">${escapeHtml(description)}</div>
    <div class="feedback-btns">
      <button class="btn-correct" data-selector="${escapeHtml(selector)}">✅ 指对了</button>
      <button class="btn-wrong" data-selector="${escapeHtml(selector)}">❌ 指错了</button>
    </div>
  `;

  // 反馈按钮事件
  card.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const isCorrect = btn.classList.contains("btn-correct");
      // 发送反馈到 Service Worker → 后端
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.SEND_MESSAGE,
        text: JSON.stringify({
          type: "feedback",
          feedback: {
            step_id: selector,
            is_correct: isCorrect,
          },
        }),
      });
      // 更新按钮状态
      btn.textContent = isCorrect ? "✅ 已记录" : "❌ 已记录";
      (btn as HTMLButtonElement).disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

/**
 * 更新球体状态显示。
 * Phase 3 实现：切换 3D 球体动画。
 */
function updateBallState(state: string): void {
  // TODO: Phase 3 - 更新 Three.js 球体动画
  console.log("[求问] 球体状态:", state);
}

/** 滚动到消息列表底部。 */
function scrollToBottom(): void {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

/**
 * HTML 转义（防止 XSS）。
 * 将特殊字符替换为 HTML 实体。
 */
function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
