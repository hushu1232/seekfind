/**
 * 求问 — Content Script: 高亮渲染引擎
 * ======================================
 *
 * 职责：
 *   1. 接收高亮指令，在页面上绘制高亮框
 *   2. 支持多种样式（pulse / glow / arrow）
 *   3. 自动消失 + 手动清除
 *   4. 样式隔离（防止页面 CSS 污染）
 *
 * 高亮框结构：
 *   <div id="qiuwen-highlight-container">  ← 固定定位的叠加层
 *     <div class="qiuwen-highlight-box">    ← 高亮框（脉冲动画）
 *     <div class="qiuwen-highlight-label">  ← 步骤标签
 *   </div>
 *
 * 性能：
 *   - 高亮框渲染 < 100ms（从收到指令到高亮可见）
 *   - 使用 CSS 动画而非 JS 动画（GPU 加速）
 */

import { INTERNAL_MSG } from "../common/constants";
import type { HighlightCommand } from "../common/types";

// ---------------------------------------------------------------------------
// 高亮容器管理
// ---------------------------------------------------------------------------

/** 高亮叠加层容器（懒创建） */
let highlightContainer: HTMLDivElement | null = null;

/**
 * 确保高亮容器存在。
 *
 * 容器特性：
 *   - position: fixed 覆盖整个视口
 *   - pointer-events: none 不拦截鼠标事件
 *   - z-index: 2147483647（最高层级）
 */
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

  // 注入动画样式（只注入一次）
  injectHighlightStyles();

  return highlightContainer;
}

/**
 * 注入高亮动画 CSS。
 * 使用 <style> 标签注入，避免与页面 CSS 冲突。
 */
function injectHighlightStyles(): void {
  if (document.getElementById("qiuwen-highlight-styles")) return;

  const style = document.createElement("style");
  style.id = "qiuwen-highlight-styles";
  style.textContent = `
    @keyframes qiuwen-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.7; transform: scale(1.02); }
    }
    @keyframes qiuwen-glow {
      0%, 100% { box-shadow: 0 0 12px rgba(74, 144, 217, 0.5); }
      50% { box-shadow: 0 0 24px rgba(74, 144, 217, 0.8); }
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// 高亮绘制
// ---------------------------------------------------------------------------

/**
 * 在页面上高亮指定元素。
 *
 * 流程：
 *   1. 通过 selector 定位目标元素
 *   2. 获取元素的 getBoundingClientRect
 *   3. 在叠加层中绘制高亮框 + 步骤标签
 *   4. 自动消失（默认 10 秒）
 *
 * @param cmd 高亮指令
 */
function highlightElement(cmd: HighlightCommand): void {
  const container = ensureContainer();

  // 尝试选择器定位
  let target = document.querySelector(cmd.selector);
  if (!target && cmd.fallback_selector) {
    target = document.querySelector(cmd.fallback_selector);
  }
  if (!target) {
    console.warn("[求问] 高亮目标未找到:", cmd.selector, cmd.fallback_selector);
    return;
  }

  const rect = target.getBoundingClientRect();

  // --- 高亮框 ---
  const box = document.createElement("div");
  box.className = "qiuwen-highlight-box";
  box.style.cssText = `
    position: absolute;
    top: ${rect.top + window.scrollY - 4}px;
    left: ${rect.left + window.scrollX - 4}px;
    width: ${rect.width + 8}px;
    height: ${rect.height + 8}px;
    border: 3px solid #4A90D9;
    border-radius: 6px;
    box-shadow: 0 0 12px rgba(74, 144, 217, 0.5), inset 0 0 12px rgba(74, 144, 217, 0.1);
    animation: qiuwen-pulse 1.5s ease-in-out infinite;
    pointer-events: none;
  `;

  // --- 步骤标签 ---
  if (cmd.description) {
    const label = document.createElement("div");
    label.className = "qiuwen-highlight-label";
    label.style.cssText = `
      position: absolute;
      top: ${rect.top + window.scrollY - 32}px;
      left: ${rect.left + window.scrollX}px;
      background: #4A90D9;
      color: white;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 13px;
      font-family: system-ui, -apple-system, sans-serif;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      pointer-events: none;
    `;
    label.textContent = `第 ${cmd.order} 步：${cmd.description}`;
    container.appendChild(label);
  }

  container.appendChild(box);

  // --- 自动消失 ---
  const duration = cmd.duration || 10000;
  setTimeout(() => {
    box.remove();
    container.querySelector(".qiuwen-highlight-label")?.remove();
  }, duration);
}

// ---------------------------------------------------------------------------
// 清除高亮
// ---------------------------------------------------------------------------

/** 清除所有高亮元素。 */
function clearHighlights(): void {
  if (highlightContainer) {
    highlightContainer.innerHTML = "";
  }
}

// ---------------------------------------------------------------------------
// 消息监听
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === INTERNAL_MSG.HIGHLIGHT) {
    highlightElement(msg.payload);
  }
  if (msg.type === INTERNAL_MSG.CLEAR_HIGHLIGHT) {
    clearHighlights();
  }
});
