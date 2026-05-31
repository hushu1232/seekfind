/**
 * 求问 — 3D 悬浮球组件
 * =======================
 *
 * 职责：
 *   1. 注入悬浮球到页面（Shadow DOM 样式隔离）
 *   2. 支持拖拽移动 + 边缘吸附
 *   3. 点击唤起 Sidebar Panel
 *   4. 四状态视觉反馈（idle/processing/success/error）
 *   5. 位置持久化（chrome.storage）
 *
 * 架构：
 *   FloatBall（主类）
 *   ├── Shadow DOM 容器（样式隔离）
 *   ├── CSS 动画球体（轻量，不依赖 Three.js）
 *   ├── 拖拽处理器（transform GPU 加速）
 *   └── 状态机（四状态驱动视觉变化）
 *
 * 设计原则：
 *   - 与 Sidebar 的 3D 球体独立，互不干扰
 *   - 无 Three.js 依赖（CSS 动画足够，节省内存）
 *   - 页面隐藏时自动暂停动画
 *   - 完全可配置（enable/position/transparency）
 */

import { INTERNAL_MSG, STORAGE_KEYS } from "../common/constants";
import { safeSend, safeStorageGet, safeStorageSet, isAlive } from "../common/chrome-safe";

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

type FloatBallState = "idle" | "processing" | "success" | "error";

interface FloatBallPrefs {
  position: { x: number; y: number };
  side: "left" | "right";
  enabled: boolean;
  transparency: number;
  lastState: FloatBallState;
}

const DEFAULT_PREFS: FloatBallPrefs = {
  position: { x: 20, y: 200 },
  side: "right",
  enabled: true,
  transparency: 0.9,
  lastState: "idle",
};

// ---------------------------------------------------------------------------
// 状态颜色配置
// ---------------------------------------------------------------------------

const STATE_COLORS: Record<FloatBallState, { primary: string; glow: string; particle: string }> = {
  idle: { primary: "#4A90D9", glow: "rgba(74,144,217,0.3)", particle: "#6BA5E7" },
  processing: { primary: "#F59E0B", glow: "rgba(245,158,11,0.4)", particle: "#FBBF24" },
  success: { primary: "#10B981", glow: "rgba(16,185,129,0.4)", particle: "#34D399" },
  error: { primary: "#EF4444", glow: "rgba(239,68,68,0.4)", particle: "#F87171" },
};

// ---------------------------------------------------------------------------
// 拖拽配置
// ---------------------------------------------------------------------------

const DRAG_THRESHOLD = 5; // px，区分点击和拖拽
const SNAP_ANIMATION_MS = 200;
const EDGE_MARGIN = 16; // 距屏幕边缘距离

// ---------------------------------------------------------------------------
// FloatBall 主类
// ---------------------------------------------------------------------------

export class FloatBall {
  private container: HTMLDivElement | null = null;
  private shadowRoot: ShadowRoot | null = null;
  private ballEl: HTMLDivElement | null = null;
  private tooltipEl: HTMLDivElement | null = null;

  // 状态
  private state: FloatBallState = "idle";
  private prefs: FloatBallPrefs = { ...DEFAULT_PREFS };

  // 拖拽状态
  private isPointerDown = false;   // 鼠标是否按下
  private isDragging = false;      // 是否进入拖拽模式（超过阈值）
  private pointerStartX = 0;       // 鼠标按下的屏幕坐标
  private pointerStartY = 0;
  private dragOffsetX = 0;         // 鼠标相对球体左上角的偏移
  private dragOffsetY = 0;
  private currentX = 0;            // 球体当前位置
  private currentY = 0;

  // 动态绑定的事件处理器（用于 removeEventListener）
  private boundMouseMove: ((e: MouseEvent) => void) | null = null;
  private boundMouseUp: ((e: MouseEvent) => void) | null = null;
  private boundTouchMove: ((e: TouchEvent) => void) | null = null;
  private boundTouchEnd: ((e: TouchEvent) => void) | null = null;

  // 动画
  private animationId: number | null = null;
  private isPageActive = true;
  private particlePhase = 0;

  // 引导
  private guideDisplayCount = 0;
  private guideTimer: ReturnType<typeof setTimeout> | null = null;

  // -----------------------------------------------------------------------
  // 初始化
  // -----------------------------------------------------------------------

  async initialize(): Promise<void> {
    // 加载偏好
    await this.loadPrefs();

    if (!this.prefs.enabled) {
      return;
    }

    // 注入 DOM
    this.inject();

    // 恢复位置
    this.restorePosition();

    // 开始动画
    this.startAnimation();

    // 监听状态更新
    this.listenStateUpdates();

    // 监听页面可见性
    this.listenVisibility();

    // 新用户引导
    this.showGuideIfNeeded();
  }

  // -----------------------------------------------------------------------
  // Shadow DOM 注入
  // -----------------------------------------------------------------------

  private inject(): void {
    this.container = document.createElement("div");
    this.container.id = "qiuwen-float-ball";
    this.container.style.cssText = `
      position: fixed;
      z-index: 2147483646;
      pointer-events: none;
    `;

    // Shadow DOM 隔离
    this.shadowRoot = this.container.attachShadow({ mode: "closed" });

    // 注入样式
    const style = document.createElement("style");
    style.textContent = this.getStyles();
    this.shadowRoot.appendChild(style);

    // 球体容器
    const ballWrapper = document.createElement("div");
    ballWrapper.className = "qw-ball-wrapper";
    ballWrapper.style.pointerEvents = "auto";

    // 球体
    this.ballEl = document.createElement("div");
    this.ballEl.className = "qw-ball idle";

    // 内部光晕
    const innerGlow = document.createElement("div");
    innerGlow.className = "qw-ball-inner";
    this.ballEl.appendChild(innerGlow);

    // 粒子容器
    const particles = document.createElement("div");
    particles.className = "qw-particles";
    this.ballEl.appendChild(particles);

    // 创建 12 个粒子
    for (let i = 0; i < 12; i++) {
      const p = document.createElement("div");
      p.className = "qw-particle";
      p.style.setProperty("--i", String(i));
      particles.appendChild(p);
    }

    ballWrapper.appendChild(this.ballEl);

    // 提示框
    this.tooltipEl = document.createElement("div");
    this.tooltipEl.className = "qw-tooltip";
    this.tooltipEl.textContent = "点击向求问提问";
    ballWrapper.appendChild(this.tooltipEl);

    this.shadowRoot.appendChild(ballWrapper);

    // 事件绑定
    this.bindEvents(ballWrapper);

    // 等待 document.body 可用（document_start 时可能不存在）
    if (document.body) {
      document.body.appendChild(this.container);
    } else {
      document.addEventListener("DOMContentLoaded", () => {
        document.body?.appendChild(this.container!);
      });
    }
  }

  // -----------------------------------------------------------------------
  // 样式
  // -----------------------------------------------------------------------

  private getStyles(): string {
    return `
      :host {
        all: initial;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      }

      .qw-ball-wrapper {
        position: relative;
        width: 56px;
        height: 56px;
        cursor: pointer;
        user-select: none;
        -webkit-user-select: none;
        filter: drop-shadow(0 2px 8px rgba(0,0,0,0.15));
        transition: filter 0.2s ease;
      }

      .qw-ball-wrapper:hover {
        filter: drop-shadow(0 4px 16px rgba(0,0,0,0.25));
      }

      .qw-ball-wrapper.dragging {
        cursor: grabbing;
        filter: drop-shadow(0 6px 20px rgba(0,0,0,0.3));
      }

      .qw-ball {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        position: relative;
        overflow: hidden;
        transition: background-color 0.3s ease, box-shadow 0.3s ease;
      }

      .qw-ball.idle {
        background: radial-gradient(circle at 35% 35%, #6BA5E7, #4A90D9, #3B7DD8);
        box-shadow: 0 0 20px rgba(74,144,217,0.3);
        animation: idle-rotate 8s linear infinite;
      }

      .qw-ball.processing {
        background: radial-gradient(circle at 35% 35%, #FBBF24, #F59E0B, #D97706);
        box-shadow: 0 0 30px rgba(245,158,11,0.4);
        animation: processing-pulse 1s ease-in-out infinite;
      }

      .qw-ball.success {
        background: radial-gradient(circle at 35% 35%, #34D399, #10B981, #059669);
        box-shadow: 0 0 25px rgba(16,185,129,0.4);
        animation: success-flash 0.3s ease;
      }

      .qw-ball.error {
        background: radial-gradient(circle at 35% 35%, #F87171, #EF4444, #DC2626);
        box-shadow: 0 0 25px rgba(239,68,68,0.4);
        animation: error-shake 0.4s ease;
      }

      .qw-ball-inner {
        position: absolute;
        top: 15%;
        left: 20%;
        width: 30%;
        height: 25%;
        background: radial-gradient(circle, rgba(255,255,255,0.6), transparent);
        border-radius: 50%;
        pointer-events: none;
      }

      /* 粒子 */
      .qw-particles {
        position: absolute;
        inset: 0;
        pointer-events: none;
      }

      .qw-particle {
        position: absolute;
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: rgba(255,255,255,0.6);
        top: 50%;
        left: 50%;
        animation: particle-orbit 4s linear infinite;
        animation-delay: calc(var(--i) * -0.33s);
      }

      .qw-ball.processing .qw-particle {
        animation-duration: 1.5s;
        background: rgba(255,255,255,0.9);
      }

      /* 提示框 */
      .qw-tooltip {
        position: absolute;
        right: calc(100% + 12px);
        top: 50%;
        transform: translateY(-50%);
        background: rgba(30,30,30,0.9);
        color: white;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 13px;
        white-space: nowrap;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease;
        backdrop-filter: blur(4px);
      }

      .qw-tooltip.visible {
        opacity: 1;
      }

      .qw-tooltip::after {
        content: "";
        position: absolute;
        left: 100%;
        top: 50%;
        transform: translateY(-50%);
        border: 5px solid transparent;
        border-left-color: rgba(30,30,30,0.9);
      }

      /* 动画关键帧 */
      @keyframes idle-rotate {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }

      @keyframes processing-pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.08); }
      }

      @keyframes success-flash {
        0% { transform: scale(1); }
        50% { transform: scale(1.15); }
        100% { transform: scale(1); }
      }

      @keyframes error-shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-4px); }
        75% { transform: translateX(4px); }
      }

      @keyframes particle-orbit {
        0% {
          transform: rotate(calc(var(--i) * 30deg)) translateX(32px) scale(1);
          opacity: 0.6;
        }
        50% {
          opacity: 1;
        }
        100% {
          transform: rotate(calc(var(--i) * 30deg + 360deg)) translateX(32px) scale(0.5);
          opacity: 0.3;
        }
      }
    `;
  }

  // -----------------------------------------------------------------------
  // 事件绑定（mousedown 时动态绑定 move/up，up 后立即移除）
  // -----------------------------------------------------------------------

  private bindEvents(wrapper: HTMLElement): void {
    // 鼠标按下
    wrapper.addEventListener("mousedown", (e) => {
      e.preventDefault();
      this.onPointerDown(e.clientX, e.clientY);

      // 动态绑定 move/up（up 后立即移除，避免残留）
      const onMove = (ev: MouseEvent) => this.onPointerMove(ev.clientX, ev.clientY);
      const onUp = () => {
        this.onPointerUp();
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // 触摸开始
    wrapper.addEventListener("touchstart", (e) => {
      e.preventDefault();
      const t = e.touches[0];
      this.onPointerDown(t.clientX, t.clientY);

      const onMove = (ev: TouchEvent) => {
        const tt = ev.touches[0];
        this.onPointerMove(tt.clientX, tt.clientY);
      };
      const onEnd = () => {
        this.onPointerUp();
        document.removeEventListener("touchmove", onMove);
        document.removeEventListener("touchend", onEnd);
      };
      document.addEventListener("touchmove", onMove, { passive: true });
      document.addEventListener("touchend", onEnd);
    }, { passive: false });

    // 鼠标悬停
    wrapper.addEventListener("mouseenter", () => {
      if (!this.isDragging) this.showTooltip();
    });
    wrapper.addEventListener("mouseleave", () => this.hideTooltip());
  }

  // -----------------------------------------------------------------------
  // 拖拽逻辑（阈值分离点击/拖拽）
  // -----------------------------------------------------------------------

  private onPointerDown(clientX: number, clientY: number): void {
    if (!this.container) return;

    const rect = this.container.getBoundingClientRect();
    this.dragOffsetX = clientX - rect.left;
    this.dragOffsetY = clientY - rect.top;
    this.pointerStartX = clientX;
    this.pointerStartY = clientY;
    this.isDragging = false;
    this.currentX = rect.left;
    this.currentY = rect.top;
  }

  private onPointerMove(clientX: number, clientY: number): void {
    const dx = Math.abs(clientX - this.pointerStartX);
    const dy = Math.abs(clientY - this.pointerStartY);

    // 超过阈值才进入拖拽模式
    if (!this.isDragging && (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD)) {
      this.isDragging = true;
      this.ballEl?.classList.add("dragging");
      this.hideTooltip();
    }

    // 只有进入拖拽模式后才更新位置
    if (this.isDragging && this.container) {
      requestAnimationFrame(() => {
        const newX = clientX - this.dragOffsetX;
        const newY = clientY - this.dragOffsetY;
        this.container!.style.left = `${newX}px`;
        this.container!.style.top = `${newY}px`;
        this.container!.style.right = "auto";
        this.container!.style.bottom = "auto";
        this.currentX = newX;
        this.currentY = newY;
      });
    }
  }

  private onPointerUp(): void {
    if (!this.isDragging) {
      // 未超过阈值 → 点击
      this.onClick();
    } else {
      // 超过阈值 → 拖拽结束
      this.ballEl?.classList.remove("dragging");
      this.snapToEdge();
      this.savePrefs();
    }

    this.isDragging = false;
  }

  // -----------------------------------------------------------------------
  // 边缘吸附
  // -----------------------------------------------------------------------

  private snapToEdge(): void {
    if (!this.container) return;

    const rect = this.container.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // 吸附到最近的边缘
    const snapLeft = rect.left < viewportWidth / 2;
    const targetX = snapLeft
      ? EDGE_MARGIN
      : viewportWidth - 56 - EDGE_MARGIN;

    // Y 轴限制在视口内
    const targetY = Math.max(EDGE_MARGIN, Math.min(rect.top, viewportHeight - 56 - EDGE_MARGIN));

    // CSS transition 动画
    this.container.style.transition = `left ${SNAP_ANIMATION_MS}ms ease, top ${SNAP_ANIMATION_MS}ms ease`;
    this.container.style.left = `${targetX}px`;
    this.container.style.top = `${targetY}px`;
    this.container.style.right = "auto";
    this.container.style.bottom = "auto";

    this.currentX = targetX;
    this.currentY = targetY;
    this.prefs.side = snapLeft ? "left" : "right";

    // 动画结束后移除 transition
    setTimeout(() => {
      if (this.container) {
        this.container.style.transition = "";
      }
    }, SNAP_ANIMATION_MS);
  }

  // -----------------------------------------------------------------------
  // 点击 → 唤起 Sidebar
  // -----------------------------------------------------------------------

  private onClick(): void {
    // 通知 Service Worker 打开侧边栏
    safeSend({ type: "FLOAT_BALL_CLICK" });
    this.hideTooltip();
  }

  // -----------------------------------------------------------------------
  // 状态管理
  // -----------------------------------------------------------------------

  setState(state: FloatBallState): void {
    if (this.state === state) return;

    this.state = state;
    this.prefs.lastState = state;

    // 更新 CSS 类
    if (this.ballEl) {
      this.ballEl.className = `qw-ball ${state}`;
    }

    // 成功/错误状态自动回归 idle
    if (state === "success") {
      setTimeout(() => this.setState("idle"), 800);
    } else if (state === "error") {
      setTimeout(() => this.setState("idle"), 1200);
    }

    this.savePrefs();
  }

  // -----------------------------------------------------------------------
  // 状态监听
  // -----------------------------------------------------------------------

  private listenStateUpdates(): void {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg.type === INTERNAL_MSG.UPDATE_BALL_STATE) {
        this.setState(msg.state);
      }
      if (msg.type === "HIDE_FLOAT_BALL") {
        this.hide();
      }
      if (msg.type === "SHOW_FLOAT_BALL") {
        this.show();
      }
    });
  }

  // -----------------------------------------------------------------------
  // 可见性控制
  // -----------------------------------------------------------------------

  private listenVisibility(): void {
    document.addEventListener("visibilitychange", () => {
      this.isPageActive = !document.hidden;
      if (this.isPageActive) {
        this.startAnimation();
      } else {
        this.stopAnimation();
      }
    });
  }

  private hide(): void {
    if (this.container) {
      this.container.style.display = "none";
    }
    this.stopAnimation();
  }

  private show(): void {
    if (this.container) {
      this.container.style.display = "block";
    }
    this.startAnimation();
  }

  // -----------------------------------------------------------------------
  // 动画（CSS 驱动，无需 requestAnimationFrame）
  // -----------------------------------------------------------------------

  private startAnimation(): void {
    // CSS 动画自动运行，无需手动驱动
  }

  private stopAnimation(): void {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  // -----------------------------------------------------------------------
  // 提示框
  // -----------------------------------------------------------------------

  private showTooltip(): void {
    if (this.tooltipEl) {
      this.tooltipEl.classList.add("visible");
    }
  }

  private hideTooltip(): void {
    if (this.tooltipEl) {
      this.tooltipEl.classList.remove("visible");
    }
  }

  // -----------------------------------------------------------------------
  // 新用户引导
  // -----------------------------------------------------------------------

  private async showGuideIfNeeded(): Promise<void> {
    const result = await safeStorageGet(["qiuwen_guide_count"]);
    this.guideDisplayCount = result.qiuwen_guide_count || 0;

    if (this.guideDisplayCount < 3) {
      setTimeout(() => {
        if (!isAlive()) return;
        this.showTooltip();
        this.guideDisplayCount++;
        safeStorageSet({ qiuwen_guide_count: this.guideDisplayCount });
        this.guideTimer = setTimeout(() => this.hideTooltip(), 3000);
      }, 1000);
    }
  }

  // -----------------------------------------------------------------------
  // 持久化
  // -----------------------------------------------------------------------

  private async loadPrefs(): Promise<void> {
    const result = await safeStorageGet([STORAGE_KEYS.FLOAT_BALL_PREFS]);
    if (result[STORAGE_KEYS.FLOAT_BALL_PREFS]) {
      this.prefs = { ...DEFAULT_PREFS, ...result[STORAGE_KEYS.FLOAT_BALL_PREFS] };
    }
  }

  private async savePrefs(): Promise<void> {
    this.prefs.position = { x: this.currentX, y: this.currentY };
    await safeStorageSet({ [STORAGE_KEYS.FLOAT_BALL_PREFS]: this.prefs });
  }

  private restorePosition(): void {
    if (!this.container) return;

    const { x, y } = this.prefs.position;
    this.container.style.left = `${x}px`;
    this.container.style.top = `${y}px`;
    this.currentX = x;
    this.currentY = y;

    // 恢复状态
    this.setState(this.prefs.lastState);
  }

  // -----------------------------------------------------------------------
  // 销毁
  // -----------------------------------------------------------------------

  dispose(): void {
    this.stopAnimation();
    if (this.guideTimer) {
      clearTimeout(this.guideTimer);
    }
    if (this.container) {
      this.container.remove();
      this.container = null;
    }
  }
}

// ---------------------------------------------------------------------------
// 自动初始化
// ---------------------------------------------------------------------------
const floatBall = new FloatBall();
floatBall.initialize().catch(() => {});
