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
 *   7. T3.3: 结构化回复渲染
 *
 * 消息流向：
 *   用户输入 → chrome.runtime.sendMessage → Service Worker → WS → 后端
 *   后端 → WS → Service Worker → chrome.runtime.onMessage → 本面板渲染
 */

import { INTERNAL_MSG, STORAGE_KEYS, API_BASE } from "../common/constants";
import type { ServerMessage, ChatMessage } from "../common/types";
import { initWelcomeFlow } from "./welcome";
import { getDiagnostics, renderDiagnosticReport } from "./diagnostics";

// ---------------------------------------------------------------------------
// 录制状态
// ---------------------------------------------------------------------------
let isRecording = false;
let currentFlowName = "";

// ---------------------------------------------------------------------------
// DOM 元素引用
// ---------------------------------------------------------------------------

const messagesEl = document.getElementById("messages")!;
const userInputEl = document.getElementById("user-input") as HTMLInputElement;
const sendBtnEl = document.getElementById("send-btn") as HTMLButtonElement;
const wsStatusEl = document.getElementById("ws-status")!;
const welcomeContainerEl = document.getElementById("welcome-container");
const diagnosticBtnEl = document.getElementById("diagnostic-btn");

let isProcessing = false;
let currentAssistantEl: HTMLDivElement | null = null;

// ---------------------------------------------------------------------------
// V12: 初始化：恢复完整状态
// ---------------------------------------------------------------------------
chrome.storage.local.get(
  [STORAGE_KEYS.CHAT_HISTORY, STORAGE_KEYS.BALL_STATE, STORAGE_KEYS.SESSION_ID],
  (data) => {
    // 恢复聊天历史（最近 50 条）
    const history: ChatMessage[] = data[STORAGE_KEYS.CHAT_HISTORY] || [];
    for (const msg of history.slice(-50)) {
      appendMessage(msg.role, msg.content, false);
    }
    scrollToBottom();

    // 恢复球体状态
    const ballState = data[STORAGE_KEYS.BALL_STATE];
    if (ballState) {
      updateBallState(ballState);
    }
  }
);

// ---------------------------------------------------------------------------
// T4.1: 新手引导
// ---------------------------------------------------------------------------
if (welcomeContainerEl) {
  const welcomeFlow = initWelcomeFlow(welcomeContainerEl);
  welcomeFlow.start();
}

// ---------------------------------------------------------------------------
// T4.2: 诊断按钮
// ---------------------------------------------------------------------------
if (diagnosticBtnEl) {
  diagnosticBtnEl.addEventListener("click", async () => {
    const diagnostics = getDiagnostics();
    const report = await diagnostics.runFullCheck();

    // 创建诊断弹窗
    const modal = document.createElement("div");
    modal.className = "diagnostic-modal";

    const modalContent = document.createElement("div");
    modalContent.className = "diagnostic-modal-content";

    const closeBtn = document.createElement("button");
    closeBtn.className = "diagnostic-modal-close";
    closeBtn.textContent = "✕";
    closeBtn.addEventListener("click", () => modal.remove());

    const reportContainer = document.createElement("div");
    reportContainer.className = "diagnostic-report";

    modalContent.appendChild(closeBtn);
    modalContent.appendChild(reportContainer);
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    renderDiagnosticReport(reportContainer, report);

    // 点击背景关闭
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.remove();
    });
  });
}

// ---------------------------------------------------------------------------
// 启动状态检测
// ---------------------------------------------------------------------------
checkSystemStatus();

async function checkSystemStatus(): Promise<void> {
  try {
    const resp = await fetch(`${API_BASE}/api/status`);
    if (!resp.ok) return;
    const status = await resp.json();

    const warnings: string[] = [];
    if (!status.ollama) warnings.push("⚠️ Ollama 未连接，AI 推理不可用");
    if (!status.chroma) warnings.push("⚠️ Chroma 未连接，文档检索不可用");
    if (!status.tts) warnings.push("💡 语音合成需要网络（或安装 pyttsx3）");
    if (!status.asr) warnings.push("💡 语音识别需要安装 Vosk 模型");
    if (!status.vision) warnings.push("💡 视觉定位需要安装 moondream2");

    if (warnings.length > 0) {
      for (const w of warnings) {
        appendMessage("assistant", w, false);
      }
    }
  } catch {
    // 后端未启动，静默忽略
  }
}

// ---------------------------------------------------------------------------
// V7: 输入长度限制 + 防抢答
// ---------------------------------------------------------------------------
const MAX_INPUT_LENGTH = 2000;
let inputDebounceTimer: ReturnType<typeof setTimeout> | null = null;
const DEBOUNCE_MS = 300;
let lastInputTime = 0;

// 设置输入框最大长度
userInputEl.maxLength = MAX_INPUT_LENGTH;

userInputEl.addEventListener("input", () => {
  lastInputTime = Date.now();
  // V7: 超长输入截断提示
  if (userInputEl.value.length > MAX_INPUT_LENGTH) {
    userInputEl.value = userInputEl.value.slice(0, MAX_INPUT_LENGTH);
  }
  if (inputDebounceTimer) clearTimeout(inputDebounceTimer);
  inputDebounceTimer = setTimeout(() => {
    inputDebounceTimer = null;
  }, DEBOUNCE_MS);
});

// ---------------------------------------------------------------------------
// 发送消息
// ---------------------------------------------------------------------------
function sendMessage(): void {
  const text = userInputEl.value.trim();
  if (!text || isProcessing) return;

  if (inputDebounceTimer) {
    clearTimeout(inputDebounceTimer);
    inputDebounceTimer = null;
    sendBtnEl.textContent = "⏳";
    setTimeout(() => {
      sendBtnEl.textContent = "发送";
      const retryText = userInputEl.value.trim();
      if (retryText && !isProcessing) {
        appendMessage("user", retryText);
        userInputEl.value = "";
        isProcessing = true;
        sendBtnEl.disabled = true;
        chrome.runtime.sendMessage({
          type: INTERNAL_MSG.SEND_MESSAGE,
          text: retryText,
          page_context: { url: window.location.href, title: document.title },
        });
      }
    }, DEBOUNCE_MS);
    return;
  }

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
// 录制控制
// ---------------------------------------------------------------------------
const recordBtnEl = document.getElementById("record-btn") as HTMLButtonElement;

if (recordBtnEl) {
  recordBtnEl.addEventListener("click", () => {
    if (isRecording) {
      stopRecording();
    } else {
      const name = prompt("输入操作流名称：");
      if (name) startRecording(name);
    }
  });
}

function startRecording(name: string): void {
  isRecording = true;
  currentFlowName = name;
  recordBtnEl.textContent = "⏹ 停止";
  recordBtnEl.classList.add("recording");
  appendMessage("assistant", `🔴 开始录制「${name}」，请在页面上执行操作...`);

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { type: INTERNAL_MSG.START_RECORDING });
    }
  });

  chrome.runtime.sendMessage({
    type: INTERNAL_MSG.SEND_MESSAGE,
    text: JSON.stringify({
      type: "flow_action",
      action: "start_recording",
      flow_name: name,
    }),
  });
}

function stopRecording(): void {
  isRecording = false;
  recordBtnEl.textContent = "⏺ 录制";
  recordBtnEl.classList.remove("recording");
  appendMessage("assistant", "⏹ 录制已停止，操作流已保存。");

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { type: INTERNAL_MSG.STOP_RECORDING });
    }
  });

  chrome.runtime.sendMessage({
    type: INTERNAL_MSG.SEND_MESSAGE,
    text: JSON.stringify({
      type: "flow_action",
      action: "stop_recording",
    }),
  });
}

// ---------------------------------------------------------------------------
// 接收消息
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== INTERNAL_MSG.RECEIVE_MESSAGE) return;

  const payload: ServerMessage = msg.payload;

  switch (payload.type) {
    case "agent_thinking": {
      currentAssistantEl = appendMessage("assistant", "", true);
      currentAssistantEl.dataset.thinkStart = String(Date.now());
      const thinkText = currentAssistantEl.querySelector(".message-text");
      if (thinkText) {
        // 安全：使用 DOM API 而非 innerHTML
        const span = document.createElement("span");
        span.className = "thinking-dots";
        span.textContent = "思考中";
        thinkText.textContent = "";
        thinkText.appendChild(span);
        animateThinkingDots(thinkText as HTMLElement);
      }
      break;
    }

    case "agent_token": {
      if (currentAssistantEl) {
        currentAssistantEl.classList.remove("thinking");
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) {
          textNode.textContent += payload.token;
        } else {
          // 安全：使用 DOM API
          const span = document.createElement("span");
          span.className = "message-text";
          span.textContent = payload.token;
          currentAssistantEl.appendChild(span);
        }
        scrollToBottom();
      }
      break;
    }

    case "agent_response": {
      if (currentAssistantEl) {
        currentAssistantEl.classList.remove("thinking");
        const textNode = currentAssistantEl.querySelector(".message-text");
        if (textNode) textNode.textContent = payload.text;
      }
      currentAssistantEl = null;
      isProcessing = false;
      sendBtnEl.disabled = false;
      sendBtnEl.textContent = "发送";
      scrollToBottom();
      break;
    }

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
// UI 组件（安全：全部使用 DOM API，无 innerHTML 拼接用户内容）
// ---------------------------------------------------------------------------

/**
 * 追加消息气泡。使用 DOM API 避免 XSS。
 * T3.3: 支持结构化回复渲染
 */
function appendMessage(role: "user" | "assistant", content: string, thinking = false): HTMLDivElement {
  const div = document.createElement("div");
  div.className = `message ${role}${thinking ? " thinking" : ""}`;
  const span = document.createElement("span");
  span.className = "message-text";

  // T3.3: 结构化回复渲染
  if (role === "assistant" && !thinking) {
    renderStructuredContent(span, content);
  } else {
    span.textContent = content;  // 安全：textContent 自动转义
  }

  div.appendChild(span);
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

/**
 * T3.3: 渲染结构化回复
 * 解析 📍 引导、📚 来源、步骤列表等格式
 */
function renderStructuredContent(container: HTMLElement, content: string): void {
  // 按行分割
  const lines = content.split("\n");

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      container.appendChild(document.createElement("br"));
      continue;
    }

    // 📍 引导行
    if (trimmed.startsWith("📍")) {
      const guideDiv = document.createElement("div");
      guideDiv.className = "structured-guide";

      const icon = document.createElement("span");
      icon.className = "guide-icon";
      icon.textContent = "📍";

      const text = document.createElement("span");
      text.className = "guide-text";
      // 解析加粗文本
      renderBoldText(text, trimmed.substring(1).trim());

      guideDiv.appendChild(icon);
      guideDiv.appendChild(text);
      container.appendChild(guideDiv);
      continue;
    }

    // 📚 来源行
    if (trimmed.startsWith("📚")) {
      const sourceDiv = document.createElement("div");
      sourceDiv.className = "structured-source";
      sourceDiv.textContent = trimmed;
      container.appendChild(sourceDiv);
      continue;
    }

    // 步骤列表 (步骤 N: 或 Step N:)
    if (/^(步骤|Step)\s*\d+[：:]/i.test(trimmed)) {
      const stepDiv = document.createElement("div");
      stepDiv.className = "structured-step";

      const numMatch = trimmed.match(/^(步骤|Step)\s*(\d+)/i);
      if (numMatch) {
        const num = document.createElement("span");
        num.className = "step-number";
        num.textContent = numMatch[2];
        stepDiv.appendChild(num);
      }

      const text = document.createElement("span");
      text.className = "step-text";
      renderBoldText(text, trimmed.replace(/^(步骤|Step)\s*\d+[：:]?\s*/i, ""));
      stepDiv.appendChild(text);

      container.appendChild(stepDiv);
      continue;
    }

    // 下一步: 行
    if (trimmed.startsWith("下一步:") || trimmed.startsWith("下一步：")) {
      const nextDiv = document.createElement("div");
      nextDiv.className = "structured-next";

      const label = document.createElement("span");
      label.className = "next-label";
      label.textContent = "下一步: ";

      const text = document.createElement("span");
      renderBoldText(text, trimmed.replace(/^下一步[：:]\s*/, ""));

      nextDiv.appendChild(label);
      nextDiv.appendChild(text);
      container.appendChild(nextDiv);
      continue;
    }

    // 普通行
    const lineDiv = document.createElement("div");
    renderBoldText(lineDiv, trimmed);
    container.appendChild(lineDiv);
  }
}

/**
 * 渲染加粗文本 (**text**)
 */
function renderBoldText(container: HTMLElement, text: string): void {
  const parts = text.split(/\*\*(.*?)\*\*/g);
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      // 加粗部分
      const strong = document.createElement("strong");
      strong.textContent = parts[i];
      container.appendChild(strong);
    } else {
      // 普通文本
      if (parts[i]) {
        container.appendChild(document.createTextNode(parts[i]));
      }
    }
  }
}

/**
 * 追加步骤卡片。使用 DOM API 构建，避免 innerHTML 拼接。
 */
function appendStepCard(
  order: number,
  description: string,
  selector: string,
  style: string = "pulse"
): void {
  const card = document.createElement("div");
  card.className = "step-card";

  const styleIcon = style === "glow" ? "✨" : style === "arrow" ? "👉" : "🔵";

  // 使用 DOM API 安全构建
  const header = document.createElement("div");
  header.className = "step-header";
  header.textContent = `${styleIcon} 第 ${order} 步`;

  const desc = document.createElement("div");
  desc.className = "step-desc";
  desc.textContent = description;

  card.appendChild(header);
  card.appendChild(desc);

  if (selector) {
    const selDiv = document.createElement("div");
    selDiv.className = "step-selector";
    selDiv.style.cssText = "font-size:11px;color:#999;margin-bottom:8px;";
    selDiv.textContent = `选择器: ${selector}`;
    card.appendChild(selDiv);
  }

  const btnContainer = document.createElement("div");
  btnContainer.className = "feedback-btns";

  const correctBtn = document.createElement("button");
  correctBtn.className = "btn-correct";
  correctBtn.dataset.step = String(order);
  correctBtn.dataset.selector = selector;
  correctBtn.textContent = "✅ 指对了";

  const wrongBtn = document.createElement("button");
  wrongBtn.className = "btn-wrong";
  wrongBtn.dataset.step = String(order);
  wrongBtn.dataset.selector = selector;
  wrongBtn.textContent = "❌ 指错了";

  btnContainer.appendChild(correctBtn);
  btnContainer.appendChild(wrongBtn);
  card.appendChild(btnContainer);

  // 反馈按钮事件
  [correctBtn, wrongBtn].forEach((btn) => {
    btn.addEventListener("click", () => {
      const isCorrect = btn.classList.contains("btn-correct");
      const stepId = btn.dataset.step || "";

      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.SEND_MESSAGE,
        text: JSON.stringify({
          type: "feedback",
          feedback: { step_id: stepId, is_correct: isCorrect },
        }),
      });

      btn.textContent = isCorrect ? "✅ 已记录" : "❌ 已记录";
      btn.disabled = true;

      const sibling = btn.classList.contains("btn-correct") ? wrongBtn : correctBtn;
      sibling.disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

/**
 * 追加截图标注卡片。使用 DOM API 安全构建。
 */
function appendScreenshotCard(imageBase64: string, description?: string): void {
  const card = document.createElement("div");
  card.className = "screenshot-card";
  card.style.cssText = "background:white;border:1px solid #e9ecef;border-radius:12px;padding:12px;margin-top:8px;max-width:100%;";

  if (description) {
    const descDiv = document.createElement("div");
    descDiv.style.cssText = "font-size:13px;color:#4A90D9;font-weight:600;margin-bottom:8px;";
    descDiv.textContent = `📸 ${description}`;
    card.appendChild(descDiv);
  }

  // 安全：base64 图片通过 img.src 设置，不经过 innerHTML
  const img = document.createElement("img");
  img.src = `data:image/png;base64,${imageBase64}`;
  img.style.cssText = "width:100%;border-radius:8px;";
  img.alt = "截图标注";
  card.appendChild(img);

  const btnContainer = document.createElement("div");
  btnContainer.className = "feedback-btns";
  btnContainer.style.marginTop = "8px";

  const correctBtn = document.createElement("button");
  correctBtn.className = "btn-correct";
  correctBtn.textContent = "✅ 位置正确";

  const wrongBtn = document.createElement("button");
  wrongBtn.className = "btn-wrong";
  wrongBtn.textContent = "❌ 位置不对";

  btnContainer.appendChild(correctBtn);
  btnContainer.appendChild(wrongBtn);
  card.appendChild(btnContainer);

  [correctBtn, wrongBtn].forEach((btn) => {
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
      btn.disabled = true;
    });
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

function updateBallState(state: string): void {
  // 生产环境不输出 console
}

function scrollToBottom(): void {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

/**
 * 思考中动画。使用 textContent 而非 innerHTML。
 */
function animateThinkingDots(el: HTMLElement): void {
  let dots = 0;
  const interval = setInterval(() => {
    if (!el.closest(".thinking")) {
      clearInterval(interval);
      return;
    }
    dots = (dots + 1) % 4;
    const dotsStr = ".".repeat(dots);
    // 安全：使用 textContent
    const span = el.querySelector(".thinking-dots");
    if (span) {
      span.textContent = `思考中${dotsStr}`;
    }
  }, 500);
}

/**
 * HTML 转义（保留用于需要 innerHTML 的边界情况）。
 */
function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
