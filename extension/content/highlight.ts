/**
 * 求问 — Content Script: 高亮渲染引擎
 * ======================================
 *
 * 职责：
 *   1. 接收高亮指令，在页面上绘制高亮框
 *   2. 支持三种样式：pulse（脉冲）/ glow（发光）/ arrow（箭头）
 *   3. 自动消失 + 手动清除
 *   4. 多步骤高亮支持
 *
 * 粒子动画已拆分到 particle.ts。
 *
 * 性能目标：高亮渲染延迟 < 100ms
 */

import { INTERNAL_MSG } from "../common/constants";
import type { HighlightCommand, HighlightStyle } from "../common/types";
import { ParticleAnimator } from "./particle";
import { addSpotlight, clearSpotlight } from "./spotlight";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------
const COLORS = { primary: "#4A90D9", primaryRgb: "74, 144, 217" };
const DEFAULT_DURATION = 10000;

// ---------------------------------------------------------------------------
// 容器管理
// ---------------------------------------------------------------------------
let highlightContainer: HTMLDivElement | null = null;
let particleCanvas: HTMLCanvasElement | null = null;
let particleAnimator: ParticleAnimator | null = null;

function ensureContainer(): HTMLDivElement {
  if (highlightContainer) return highlightContainer;

  highlightContainer = document.createElement("div");
  highlightContainer.id = "qiuwen-highlight-container";
  highlightContainer.style.cssText = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none; z-index: 2147483647;
  `;

  // 粒子 Canvas
  particleCanvas = document.createElement("canvas");
  particleCanvas.id = "qiuwen-particle-canvas";
  particleCanvas.style.cssText = `
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none;
  `;
  const dpr = window.devicePixelRatio || 1;
  particleCanvas.width = window.innerWidth * dpr;
  particleCanvas.height = window.innerHeight * dpr;
  const ctx = particleCanvas.getContext("2d");
  if (ctx) ctx.scale(dpr, dpr);

  highlightContainer.appendChild(particleCanvas);
  document.documentElement.appendChild(highlightContainer);

  if (ctx) particleAnimator = new ParticleAnimator(particleCanvas, ctx);
  injectHighlightStyles();

  window.addEventListener("resize", () => {
    if (particleCanvas && ctx) {
      const dpr = window.devicePixelRatio || 1;
      particleCanvas.width = window.innerWidth * dpr;
      particleCanvas.height = window.innerHeight * dpr;
      ctx.scale(dpr, dpr);
    }
  });

  return highlightContainer;
}

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
      0%, 100% { box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5); }
      50% { box-shadow: 0 0 28px rgba(${COLORS.primaryRgb}, 0.9), 0 0 56px rgba(${COLORS.primaryRgb}, 0.3); }
    }
    .qiuwen-highlight-box.style-pulse {
      border: 3px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5), inset 0 0 12px rgba(${COLORS.primaryRgb}, 0.1);
      animation: qiuwen-pulse 1.5s ease-in-out infinite;
    }
    .qiuwen-highlight-box.style-glow {
      border: 2px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5);
      animation: qiuwen-glow 2s ease-in-out infinite;
    }
    .qiuwen-highlight-box.style-arrow {
      border: 3px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5);
    }
    .qiuwen-highlight-arrow {
      position: absolute; width: 0; height: 0;
      border-left: 10px solid transparent;
      border-right: 10px solid transparent;
      border-bottom: 16px solid ${COLORS.primary};
      filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
    }
    .qiuwen-highlight-label {
      background: ${COLORS.primary}; color: white;
      padding: 4px 10px; border-radius: 4px;
      font-size: 13px; font-family: system-ui, sans-serif;
      white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      pointer-events: none; position: absolute;
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// 高亮绘制
// ---------------------------------------------------------------------------
function highlightElement(cmd: HighlightCommand): void {
  const container = ensureContainer();

  let target = document.querySelector(cmd.selector);
  if (!target && cmd.fallback_selector) target = document.querySelector(cmd.fallback_selector);
  if (!target) { console.warn("[求问] 高亮目标未找到:", cmd.selector); return; }

  const rect = target.getBoundingClientRect();
  const style: HighlightStyle = cmd.style || "pulse";
  const duration = cmd.duration || DEFAULT_DURATION;

  // 聚光灯效果（T3.1 新增）
  if (style === "spotlight") {
    if (target instanceof HTMLElement) {
      addSpotlight(target, { duration });
    }
    return;
  }

  // 高亮框
  const box = document.createElement("div");
  box.className = `qiuwen-highlight-box style-${style}`;
  box.style.cssText = `
    position: absolute;
    top: ${rect.top + window.scrollY - 4}px;
    left: ${rect.left + window.scrollX - 4}px;
    width: ${rect.width + 8}px; height: ${rect.height + 8}px;
    border-radius: 6px; pointer-events: none;
    transition: opacity 0.3s ease;
  `;

  // 箭头
  if (style === "arrow") {
    const arrow = document.createElement("div");
    arrow.className = "qiuwen-highlight-arrow";
    arrow.style.cssText = `
      position: absolute;
      top: ${rect.top + window.scrollY - 20}px;
      left: ${rect.left + window.scrollX + rect.width / 2 - 10}px;
    `;
    container.appendChild(arrow);
    setTimeout(() => arrow.remove(), duration);
  }

  // 标签
  if (cmd.description) {
    const label = document.createElement("div");
    label.className = "qiuwen-highlight-label";
    label.style.cssText = `
      top: ${rect.top + window.scrollY - 32}px;
      left: ${rect.left + window.scrollX}px;
    `;
    label.textContent = `第 ${cmd.order} 步：${cmd.description}`;
    container.appendChild(label);
    setTimeout(() => label.remove(), duration);
  }

  container.appendChild(box);

  // 粒子动画
  particleAnimator?.start(rect);

  // 自动消失
  setTimeout(() => {
    box.style.opacity = "0";
    setTimeout(() => box.remove(), 300);
  }, duration);
}

function clearHighlights(): void {
  if (highlightContainer) highlightContainer.innerHTML = "";
  particleAnimator?.stop();
  clearSpotlight(); // T3.1: 清除聚光灯
}

// ---------------------------------------------------------------------------
// 消息监听
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === INTERNAL_MSG.HIGHLIGHT) highlightElement(msg.payload);
  if (msg.type === INTERNAL_MSG.CLEAR_HIGHLIGHT) clearHighlights();
});
