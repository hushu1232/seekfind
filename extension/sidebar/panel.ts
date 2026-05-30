/**
 * 求问 — Sidebar 对话面板
 * 管理消息列表、输入框、与 Service Worker 通信。
 */

import { INTERNAL_MSG, STORAGE_KEYS } from "../common/constants";
import type { ServerMessage, ChatMessage } from "../common/types";

// ---------------------------------------------------------------------------
// DOM 元素
// ---------------------------------------------------------------------------
const messagesEl = document.getElementById("messages")!;
const userInputEl = document.getElementById("user-input") as HTMLInputElement;
const sendBtnEl = document.getElementById("send-btn") as HTMLButtonElement;
const wsStatusEl = document.getElementById("ws-status")!;
const ballContainerEl = document.getElementById("ball-container")!;

let isProcessing = false;
let currentAssistantEl: HTMLDivElement | null = null;

// ---------------------------------------------------------------------------
// 初始化：恢复聊天历史
// ---------------------------------------------------------------------------
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
function sendMessage(): void {
  const text = userInputEl.value.trim();
  if (!text || isProcessing) return;

  // 显示用户消息
  appendMessage("user", text);
  userInputEl.value = "";

  // 发送到 Service Worker
  isProcessing = true;
  sendBtnEl.disabled = true;

  chrome.runtime.sendMessage({
    type: INTERNAL_MSG.SEND_MESSAGE,
    text,
    page_context: { url: window.location.href, title: document.title },
  });
}

sendBtnEl.addEventListener("click", sendMessage);
userInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// ---------------------------------------------------------------------------
// 接收消息
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== INTERNAL_MSG.RECEIVE_MESSAGE) return;

  const payload: ServerMessage = msg.payload;

  switch (payload.type) {
    case "agent_thinking":
      currentAssistantEl = appendMessage("assistant", "🤔 正在思考...", true);
      break;

    case "agent_token":
      if (currentAssistantEl) {
        // 追加 token
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) {
          // 移除 thinking 样式
          currentAssistantEl.classList.remove("thinking");
          textNode.textContent += payload.token;
        } else {
          currentAssistantEl.innerHTML = `<span class="message-text">${escapeHtml(payload.token)}</span>`;
        }
        scrollToBottom();
      }
      break;

    case "agent_response":
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
      // 显示步骤卡片
      appendStepCard(payload.order, payload.description, payload.selector);
      break;

    case "proactive_hint":
      appendMessage("assistant", `💡 ${payload.message}`);
      break;
  }

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
// UI 辅助
// ---------------------------------------------------------------------------
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
      btn.textContent = isCorrect ? "✅ 已记录" : "❌ 已记录";
      btn.disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

function updateBallState(state: string): void {
  // Phase 3: 更新 3D 球体状态
  console.log("[求问] 球体状态:", state);
}

function scrollToBottom(): void {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
