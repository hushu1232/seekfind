/**
 * 求问 — Content Script: 高亮渲染引擎
 * 在页面上绘制高亮框、光点粒子动画。
 */

import { INTERNAL_MSG } from "../common/constants";
import type { HighlightCommand } from "../common/types";

// ---------------------------------------------------------------------------
// 高亮容器（Shadow DOM 隔离）
// ---------------------------------------------------------------------------
let highlightContainer: HTMLDivElement | null = null;

function ensureContainer(): HTMLDivElement {
  if (highlightContainer) return highlightContainer;

  highlightContainer = document.createElement("div");
  highlightContainer.id = "qiuwen-highlight-container";
  highlightContainer.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 2147483647;
  `;
  document.documentElement.appendChild(highlightContainer);
  return highlightContainer;
}

// ---------------------------------------------------------------------------
// 高亮绘制
// ---------------------------------------------------------------------------
function highlightElement(cmd: HighlightCommand): void {
  const container = ensureContainer();

  // 尝试选择器定位
  let target = document.querySelector(cmd.selector);
  if (!target && cmd.fallback_selector) {
    target = document.querySelector(cmd.fallback_selector);
  }
  if (!target) {
    console.warn("[求问] 高亮目标未找到:", cmd.selector);
    return;
  }

  const rect = target.getBoundingClientRect();

  // 创建高亮框
  const box = document.createElement("div");
  box.className = "qiuwen-highlight-box";
  box.style.cssText = `
    position: absolute;
    top: ${rect.top - 4}px;
    left: ${rect.left - 4}px;
    width: ${rect.width + 8}px;
    height: ${rect.height + 8}px;
    border: 3px solid #4A90D9;
    border-radius: 6px;
    box-shadow: 0 0 12px rgba(74, 144, 217, 0.5), inset 0 0 12px rgba(74, 144, 217, 0.1);
    animation: qiuwen-pulse 1.5s ease-in-out infinite;
    pointer-events: none;
  `;

  // 添加步骤标签
  if (cmd.description) {
    const label = document.createElement("div");
    label.className = "qiuwen-highlight-label";
    label.style.cssText = `
      position: absolute;
      top: ${rect.top - 32}px;
      left: ${rect.left}px;
      background: #4A90D9;
      color: white;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 13px;
      font-family: system-ui, sans-serif;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;
    label.textContent = `第 ${cmd.order} 步：${cmd.description}`;
    container.appendChild(label);
  }

  container.appendChild(box);

  // 注入动画样式
  if (!document.getElementById("qiuwen-highlight-styles")) {
    const style = document.createElement("style");
    style.id = "qiuwen-highlight-styles";
    style.textContent = `
      @keyframes qiuwen-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.7; transform: scale(1.02); }
      }
    `;
    document.head.appendChild(style);
  }

  // 自动消失（10 秒后）
  setTimeout(() => {
    box.remove();
    container.querySelector(".qiuwen-highlight-label")?.remove();
  }, 10000);
}

// ---------------------------------------------------------------------------
// 清除所有高亮
// ---------------------------------------------------------------------------
function clearHighlights(): void {
  if (highlightContainer) {
    highlightContainer.innerHTML = "";
  }
}

// ---------------------------------------------------------------------------
// 监听消息
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === INTERNAL_MSG.HIGHLIGHT) {
    highlightElement(msg.payload);
  }
  if (msg.type === INTERNAL_MSG.CLEAR_HIGHLIGHT) {
    clearHighlights();
  }
});
