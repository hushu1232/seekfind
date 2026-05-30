/**
 * 求问 — Sidebar 对话面板
 * =========================
 *
 * 职责：
 *   1. 渲染消息列表（user / assistant 消息）
 *   2. 处理用户输入（发送到 Service Worker）
 *   3. 接收并显示 Agent 的流式回复
 *   4. 显示步骤卡片（分步指引 + 高亮 + 反馈按钮）
 *   5. 显示截图标注（base64 图片）
 *   6. 恢复聊天历史
 *
 * 消息流向：
 *   用户输入 → chrome.runtime.sendMessage → Service Worker → WS → 后端
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

  appendMessage("user", text);
  userInputEl.value = "";
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
      if (currentAssistantEl) {
        currentAssistantEl.classList.remove("thinking");
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) textNode.textContent = payload.text;
      }
      currentAssistantEl = null;
      isProcessing = false;
      sendBtnEl.disabled = false;
      scrollToBottom();
      break;

    case "highlight":
      appendStepCard(payload.order, payload.description, payload.selector, payload.style);
      break;

    case "screenshot_annotated":
      appendScreenshotCard(payload.image_base64, payload.description);
      break;

    case "proactive_hint":
      appendMessage("assistant", `💡 ${payload.message}`);
      break;
  }

  if (msg.type === INTERNAL_MSG.WS_CONNECTED) wsStatusEl.classList.add("connected");
  if (msg.type === INTERNAL_MSG.WS_DISCONNECTED) wsStatusEl.classList.remove("connected");
  if (msg.type === INTERNAL_MSG.UPDATE_BALL_STATE) updateBallState(msg.state);
});

// ---------------------------------------------------------------------------
// UI 组件
// ---------------------------------------------------------------------------

/**
 * 追加消息气泡。
 */
function appendMessage(role: "user" | "assistant", content: string, thinking = false): HTMLDivElement {
  const div = document.createElement("div");
  div.className = `message ${role}${thinking ? " thinking" : ""}`;
  div.innerHTML = `<span class="message-text">${escapeHtml(content)}</span>`;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

/**
 * 追加步骤卡片（分步指引 + 反馈按钮）。
 *
 * 结构：
 *   ┌─────────────────────────┐
 *   │  第 N 步                │
 *   │  描述文字               │
 *   │                         │
 *   │  [✅ 指对了]  [❌ 指错了] │
 *   └─────────────────────────┘
 */
function appendStepCard(
  order: number,
  description: string,
  selector: string,
  style: string = "pulse"
): void {
  const card = document.createElement("div");
  card.className = "step-card";

  // 样式指示器
  const styleIcon = style === "glow" ? "✨" : style === "arrow" ? "👉" : "🔵";

  card.innerHTML = `
    <div class="step-header">${styleIcon} 第 ${order} 步</div>
    <div class="step-desc">${escapeHtml(description)}</div>
    ${selector ? `<div class="step-selector" style="font-size:11px;color:#999;margin-bottom:8px;">选择器: ${escapeHtml(selector)}</div>` : ""}
    <div class="feedback-btns">
      <button class="btn-correct" data-step="${order}" data-selector="${escapeHtml(selector)}">✅ 指对了</button>
      <button class="btn-wrong" data-step="${order}" data-selector="${escapeHtml(selector)}">❌ 指错了</button>
    </div>
  `;

  // 反馈按钮事件
  card.querySelectorAll(".feedback-btns button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const isCorrect = btn.classList.contains("btn-correct");
      const stepId = (btn as HTMLElement).dataset.step || "";

      // 发送反馈
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.SEND_MESSAGE,
        text: JSON.stringify({
          type: "feedback",
          feedback: { step_id: stepId, is_correct: isCorrect },
        }),
      });

      // 更新 UI
      btn.textContent = isCorrect ? "✅ 已记录" : "❌ 已记录";
      (btn as HTMLButtonElement).disabled = true;

      // 禁用另一个按钮
      const sibling = btn.classList.contains("btn-correct")
        ? btn.parentElement?.querySelector(".btn-wrong")
        : btn.parentElement?.querySelector(".btn-correct");
      if (sibling) (sibling as HTMLButtonElement).disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

/**
 * 追加截图标注卡片。
 *
 * 显示后端返回的标注后截图（base64 PNG）。
 */
function appendScreenshotCard(imageBase64: string, description?: string): void {
  const card = document.createElement("div");
  card.className = "screenshot-card";
  card.style.cssText = `
    background: white;
    border: 1px solid #e9ecef;
    border-radius: 12px;
    padding: 12px;
    margin-top: 8px;
    max-width: 100%;
  `;

  card.innerHTML = `
    ${description ? `<div style="font-size:13px;color:#4A90D9;font-weight:600;margin-bottom:8px;">📸 ${escapeHtml(description)}</div>` : ""}
    <img src="data:image/png;base64,${imageBase64}" style="width:100%;border-radius:8px;" alt="截图标注" />
    <div class="feedback-btns" style="margin-top:8px;">
      <button class="btn-correct">✅ 位置正确</button>
      <button class="btn-wrong">❌ 位置不对</button>
    </div>
  `;

  // 反馈按钮
  card.querySelectorAll(".feedback-btns button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const isCorrect = btn.classList.contains("btn-correct");
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.SEND_MESSAGE,
        text: JSON.stringify({
          type: "feedback",
          feedback: { step_id: "screenshot", is_correct: isCorrect },
        }),
      });
      btn.textContent = isCorrect ? "✅ 已记录" : "❌ 已记录";
      (btn as HTMLButtonElement).disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

function updateBallState(state: string): void {
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
