/**
 * 求问 — Content Script: 高亮渲染引擎
 * ======================================
 *
 * 职责：
 *   1. 接收高亮指令，在页面上绘制高亮框
 *   2. 支持三种样式：pulse（脉冲）/ glow（发光）/ arrow（箭头）
 *   3. Canvas 光点粒子动画（从球体飞向目标）
 *   4. 自动消失 + 手动清除
 *   5. 多步骤高亮支持（同时高亮多个元素）
 *
 * 高亮框结构：
 *   <div id="qiuwen-highlight-container">     ← 固定定位叠加层
 *     <canvas id="qiuwen-particle-canvas">     ← 粒子动画层
 *     <div class="qiuwen-highlight-box ...">   ← 高亮框（按样式类名区分）
 *     <div class="qiuwen-highlight-label">     ← 步骤标签
 *   </div>
 *
 * 性能目标：
 *   - 高亮渲染延迟 < 100ms（从收到指令到高亮可见）
 *   - 粒子动画 60fps（requestAnimationFrame）
 *   - 自动清理，防止 DOM 泄漏
 */

import { INTERNAL_MSG } from "../common/constants";
import type { HighlightCommand } from "../common/types";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/** 高亮样式类型 */
type HighlightStyle = "pulse" | "glow" | "arrow";

/** 默认高亮持续时间（毫秒） */
const DEFAULT_DURATION = 10000;

/** 颜色常量 */
const COLORS = {
  primary: "#4A90D9",
  primaryRgb: "74, 144, 217",
  success: "#28a745",
  danger: "#dc3545",
};

// ---------------------------------------------------------------------------
// 高亮容器管理
// ---------------------------------------------------------------------------

/** 高亮叠加层容器（懒创建） */
let highlightContainer: HTMLDivElement | null = null;

/** 粒子动画 Canvas */
let particleCanvas: HTMLCanvasElement | null = null;
let particleCtx: CanvasRenderingContext2D | null = null;

/** 活跃的粒子动画 ID（用于取消） */
let activeParticleAnimId: number | null = null;

/** 当前高亮的元素数量 */
let activeHighlightCount = 0;

/**
 * 确保高亮容器和 Canvas 存在。
 *
 * 容器特性：
 *   - position: fixed 覆盖整个视口
 *   - pointer-events: none 不拦截鼠标事件
 *   - z-index: 2147483647（最高层级）
 *   - Canvas 层在高亮框下方
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

  // 创建粒子 Canvas（底层）
  particleCanvas = document.createElement("canvas");
  particleCanvas.id = "qiuwen-particle-canvas";
  particleCanvas.style.cssText = `
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  `;
  // 设置 Canvas 分辨率匹配设备像素比
  const dpr = window.devicePixelRatio || 1;
  particleCanvas.width = window.innerWidth * dpr;
  particleCanvas.height = window.innerHeight * dpr;
  particleCtx = particleCanvas.getContext("2d");
  if (particleCtx) {
    particleCtx.scale(dpr, dpr);
  }

  highlightContainer.appendChild(particleCanvas);
  document.documentElement.appendChild(highlightContainer);

  // 注入动画样式
  injectHighlightStyles();

  // 窗口大小变化时调整 Canvas
  window.addEventListener("resize", () => {
    if (particleCanvas && particleCtx) {
      const dpr = window.devicePixelRatio || 1;
      particleCanvas.width = window.innerWidth * dpr;
      particleCanvas.height = window.innerHeight * dpr;
      particleCtx.scale(dpr, dpr);
    }
  });

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
    /* --- 脉冲样式 --- */
    @keyframes qiuwen-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.7; transform: scale(1.02); }
    }
    .qiuwen-highlight-box.style-pulse {
      border: 3px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5),
                  inset 0 0 12px rgba(${COLORS.primaryRgb}, 0.1);
      animation: qiuwen-pulse 1.5s ease-in-out infinite;
    }

    /* --- 发光样式 --- */
    @keyframes qiuwen-glow {
      0%, 100% { box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5); }
      50% { box-shadow: 0 0 28px rgba(${COLORS.primaryRgb}, 0.9), 0 0 56px rgba(${COLORS.primaryRgb}, 0.3); }
    }
    .qiuwen-highlight-box.style-glow {
      border: 2px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5);
      animation: qiuwen-glow 2s ease-in-out infinite;
    }

    /* --- 箭头样式 --- */
    .qiuwen-highlight-box.style-arrow {
      border: 3px solid ${COLORS.primary};
      box-shadow: 0 0 12px rgba(${COLORS.primaryRgb}, 0.5);
    }
    .qiuwen-highlight-arrow {
      position: absolute;
      width: 0;
      height: 0;
      border-left: 10px solid transparent;
      border-right: 10px solid transparent;
      border-bottom: 16px solid ${COLORS.primary};
      filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
    }

    /* --- 标签 --- */
    .qiuwen-highlight-label {
      background: ${COLORS.primary};
      color: white;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 13px;
      font-family: system-ui, -apple-system, sans-serif;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      pointer-events: none;
      position: absolute;
    }

    /* --- 反馈指示器 --- */
    @keyframes qiuwen-feedback-pop {
      0% { transform: scale(0); opacity: 0; }
      50% { transform: scale(1.2); opacity: 1; }
      100% { transform: scale(1); opacity: 1; }
    }
    .qiuwen-feedback-indicator {
      animation: qiuwen-feedback-pop 0.3s ease-out;
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
 *   1. 通过 selector 定位目标元素（支持 fallback）
 *   2. 获取元素的 getBoundingClientRect
 *   3. 根据样式类型绘制高亮框
 *   4. 添加步骤标签
 *   5. 可选：启动粒子动画
 *   6. 自动消失（duration 毫秒后）
 *
 * @param cmd 高亮指令
 */
function highlightElement(cmd: HighlightCommand): void {
  const container = ensureContainer();

  // --- 选择器定位 ---
  let target = document.querySelector(cmd.selector);
  if (!target && cmd.fallback_selector) {
    target = document.querySelector(cmd.fallback_selector);
  }
  if (!target) {
    console.warn("[求问] 高亮目标未找到:", cmd.selector, cmd.fallback_selector);
    return;
  }

  const rect = target.getBoundingClientRect();
  const style: HighlightStyle = cmd.style || "pulse";
  const duration = cmd.duration || DEFAULT_DURATION;

  // --- 高亮框 ---
  const box = document.createElement("div");
  box.className = `qiuwen-highlight-box style-${style}`;
  box.style.cssText = `
    position: absolute;
    top: ${rect.top + window.scrollY - 4}px;
    left: ${rect.left + window.scrollX - 4}px;
    width: ${rect.width + 8}px;
    height: ${rect.height + 8}px;
    border-radius: 6px;
    pointer-events: none;
    transition: opacity 0.3s ease;
  `;

  // --- 箭头样式：在高亮框上方添加箭头 ---
  if (style === "arrow") {
    const arrow = document.createElement("div");
    arrow.className = "qiuwen-highlight-arrow";
    arrow.style.cssText = `
      position: absolute;
      top: ${rect.top + window.scrollY - 20}px;
      left: ${rect.left + window.scrollX + rect.width / 2 - 10}px;
    `;
    container.appendChild(arrow);

    // 箭头也随高亮框消失
    setTimeout(() => arrow.remove(), duration);
  }

  // --- 步骤标签 ---
  if (cmd.description) {
    const label = document.createElement("div");
    label.className = "qiuwen-highlight-label";
    label.style.cssText = `
      top: ${rect.top + window.scrollY - 32}px;
      left: ${rect.left + window.scrollX}px;
    `;
    label.textContent = `第 ${cmd.order} 步：${cmd.description}`;
    container.appendChild(label);

    // 标签随高亮框消失
    setTimeout(() => label.remove(), duration);
  }

  container.appendChild(box);
  activeHighlightCount++;

  // --- 自动消失 ---
  setTimeout(() => {
    box.style.opacity = "0";
    setTimeout(() => {
      box.remove();
      activeHighlightCount--;
    }, 300);
  }, duration);
}

// ---------------------------------------------------------------------------
// 粒子动画
// ---------------------------------------------------------------------------

/**
 * 粒子类。
 * 从起始位置飞向目标位置，带拖尾效果。
 */
class Particle {
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  size: number;
  speed: number;
  opacity: number;
  trail: { x: number; y: number; opacity: number }[];
  color: string;

  constructor(
    startX: number,
    startY: number,
    targetX: number,
    targetY: number
  ) {
    this.x = startX;
    this.y = startY;
    this.targetX = targetX;
    this.targetY = targetY;
    this.size = 2 + Math.random() * 3;
    this.speed = 0.02 + Math.random() * 0.03;
    this.opacity = 1;
    this.trail = [];
    this.color = COLORS.primary;
  }

  /**
   * 更新粒子位置。
   * 使用线性插值向目标移动，速度逐渐加快。
   * @returns true 如果粒子已到达目标
   */
  update(): boolean {
    // 保存拖尾
    this.trail.push({ x: this.x, y: this.y, opacity: this.opacity });
    if (this.trail.length > 8) this.trail.shift();

    // 线性插值移动
    const dx = this.targetX - this.x;
    const dy = this.targetY - this.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 5) return true; // 到达目标

    this.x += dx * this.speed;
    this.y += dy * this.speed;
    this.speed = Math.min(this.speed + 0.001, 0.08); // 加速

    return false;
  }

  /** 绘制粒子和拖尾。 */
  draw(ctx: CanvasRenderingContext2D): void {
    // 绘制拖尾
    for (let i = 0; i < this.trail.length; i++) {
      const t = this.trail[i];
      const alpha = (i / this.trail.length) * 0.5;
      ctx.beginPath();
      ctx.arc(t.x, t.y, this.size * 0.5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${COLORS.primaryRgb}, ${alpha})`;
      ctx.fill();
    }

    // 绘制粒子本体
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${COLORS.primaryRgb}, ${this.opacity})`;
    ctx.fill();

    // 发光效果
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size * 2, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${COLORS.primaryRgb}, 0.15)`;
    ctx.fill();
  }
}

/**
 * 启动粒子动画。
 *
 * 粒子从页面中心（球体位置估计）飞向目标元素中心。
 * 使用 requestAnimationFrame 实现 60fps 流畅动画。
 *
 * @param targetRect 目标元素的矩形区域
 * @param particleCount 粒子数量（默认 12）
 */
function startParticleAnimation(
  targetRect: DOMRect,
  particleCount: number = 12
): void {
  if (!particleCtx || !particleCanvas) return;

  // 目标位置（元素中心）
  const targetX = targetRect.left + targetRect.width / 2;
  const targetY = targetRect.top + targetRect.height / 2;

  // 起始位置（页面右侧偏上，模拟球体位置）
  const startX = window.innerWidth - 50;
  const startY = window.innerHeight / 2;

  // 创建粒子
  const particles: Particle[] = [];
  for (let i = 0; i < particleCount; i++) {
    particles.push(
      new Particle(
        startX + (Math.random() - 0.5) * 40,
        startY + (Math.random() - 0.5) * 40,
        targetX + (Math.random() - 0.5) * 20,
        targetY + (Math.random() - 0.5) * 20
      )
    );
  }

  // 动画循环
  function animate() {
    if (!particleCtx || !particleCanvas) return;

    // 清除 Canvas
    particleCtx.clearRect(
      0,
      0,
      particleCanvas.width / (window.devicePixelRatio || 1),
      particleCanvas.height / (window.devicePixelRatio || 1)
    );

    // 更新和绘制每个粒子
    let allDone = true;
    for (const p of particles) {
      const done = p.update();
      p.draw(particleCtx);
      if (!done) allDone = false;
    }

    // 所有粒子到达目标后停止
    if (!allDone) {
      activeParticleAnimId = requestAnimationFrame(animate);
    } else {
      // 清除 Canvas
      particleCtx.clearRect(
        0,
        0,
        particleCanvas.width / (window.devicePixelRatio || 1),
        particleCanvas.height / (window.devicePixelRatio || 1)
      );
      activeParticleAnimId = null;
    }
  }

  // 取消之前的动画
  if (activeParticleAnimId) {
    cancelAnimationFrame(activeParticleAnimId);
  }
  activeParticleAnimId = requestAnimationFrame(animate);
}

// ---------------------------------------------------------------------------
// 清除高亮
// ---------------------------------------------------------------------------

/** 清除所有高亮元素和粒子动画。 */
function clearHighlights(): void {
  if (highlightContainer) {
    // 保留 Canvas，清除其他元素
    const canvas = highlightContainer.querySelector("canvas");
    highlightContainer.innerHTML = "";
    if (canvas) highlightContainer.appendChild(canvas);
  }
  if (activeParticleAnimId) {
    cancelAnimationFrame(activeParticleAnimId);
    activeParticleAnimId = null;
  }
  if (particleCtx && particleCanvas) {
    particleCtx.clearRect(
      0,
      0,
      particleCanvas.width / (window.devicePixelRatio || 1),
      particleCanvas.height / (window.devicePixelRatio || 1)
    );
  }
  activeHighlightCount = 0;
}

// ---------------------------------------------------------------------------
// 消息监听
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === INTERNAL_MSG.HIGHLIGHT) {
    const cmd: HighlightCommand = msg.payload;
    highlightElement(cmd);

    // 同时启动粒子动画
    const selector = cmd.selector;
    const target = document.querySelector(selector);
    if (target) {
      const rect = target.getBoundingClientRect();
      startParticleAnimation(rect);
    }
  }
  if (msg.type === INTERNAL_MSG.CLEAR_HIGHLIGHT) {
    clearHighlights();
  }
});
