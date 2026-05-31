/**
 * 求问 — 骨架预埋模块
 * =====================
 *
 * 职责：
 *   1. 页面加载时立即显示 CSS 2D 骨架球（< 50ms）
 *   2. Three.js 异步加载完成后无感切换为 3D 球
 *   3. WebGL 不可用时保留 2D 骨架（降级方案）
 *
 * 性能目标：
 *   - 骨架球出现 < 50ms（纯 CSS，不依赖 JS 库）
 *   - 3D 球加载 < 1500ms（Three.js 动态 import）
 *   - 切换过程无闪烁（opacity 过渡）
 *
 * 架构：
 *   skeleton.ts 负责"快速显示"，ball.ts 负责"3D 渲染"。
 *   两者通过 Ball3D 实例协作：骨架先占位，3D 就绪后替换。
 */

import { Ball3D } from "./ball";
import type { BallState } from "../common/types";

// ---------------------------------------------------------------------------
// SkeletonBall 类
// ---------------------------------------------------------------------------

export class SkeletonBall {
  private container: HTMLElement;
  private skeletonEl: HTMLDivElement | null = null;
  private ball3d: Ball3D | null = null;
  private stateIndicator: HTMLDivElement | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  /**
   * 初始化骨架球。
   *
   * 流程：
   *   1. 立即注入 CSS 2D 骨架（< 50ms）
   *   2. 异步创建 Ball3D 实例（加载 Three.js）
   *   3. 3D 就绪后无感切换
   */
  async initialize(): Promise<void> {
    // Step 1: 立即显示骨架（同步，< 50ms）
    this.injectSkeleton();

    // Step 2: 异步加载 3D 球体
    try {
      this.ball3d = new Ball3D(this.container);
      await this.ball3d.initialize();

      // Step 3: 3D 就绪，无感切换
      this.transitionTo3D();
    } catch (e) {
      console.warn("[SkeletonBall] 3D 加载失败，保留 2D 骨架", e);
      // 保留 2D 骨架，不报错
    }
  }

  /**
   * 注入 CSS 2D 骨架球。
   *
   * 使用纯 CSS 实现：
   *   - 蓝白渐变圆形
   *   - 脉冲动画
   *   - 状态指示器
   *
   * 不依赖任何 JS 库，确保 < 50ms 渲染。
   */
  private injectSkeleton(): void {
    // 注入样式
    const style = document.createElement("style");
    style.textContent = `
      .qiuwen-skeleton-ball {
        width: 120px;
        height: 120px;
        border-radius: 50%;
        background: linear-gradient(135deg, #4A90D9 0%, #6BA5E7 50%, #8CC4F0 100%);
        box-shadow: 0 4px 20px rgba(74, 144, 217, 0.4);
        animation: qiuwen-skeleton-pulse 2s ease-in-out infinite;
        position: relative;
      }
      @keyframes qiuwen-skeleton-pulse {
        0%, 100% { transform: scale(1); opacity: 0.85; }
        50% { transform: scale(1.05); opacity: 1; }
      }
      .qiuwen-skeleton-eyes {
        position: absolute;
        top: 40%;
        left: 50%;
        transform: translate(-50%, -50%);
        display: flex;
        gap: 16px;
      }
      .qiuwen-skeleton-eye {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: white;
        animation: qiuwen-blink 3s ease-in-out infinite;
      }
      .qiuwen-skeleton-eye:nth-child(2) {
        animation-delay: 0.1s;
      }
      @keyframes qiuwen-blink {
        0%, 45%, 55%, 100% { transform: scaleY(1); }
        50% { transform: scaleY(0.1); }
      }
      .qiuwen-skeleton-state {
        position: absolute;
        bottom: -24px;
        left: 50%;
        transform: translateX(-50%);
        font-size: 11px;
        color: #6c757d;
        white-space: nowrap;
      }
    `;
    this.container.appendChild(style);

    // 创建骨架球
    this.skeletonEl = document.createElement("div");
    this.skeletonEl.className = "qiuwen-skeleton-ball";

    // 眼睛
    const eyes = document.createElement("div");
    eyes.className = "qiuwen-skeleton-eyes";
    eyes.innerHTML = `<div class="qiuwen-skeleton-eye"></div><div class="qiuwen-skeleton-eye"></div>`;
    this.skeletonEl.appendChild(eyes);

    // 状态指示器
    this.stateIndicator = document.createElement("div");
    this.stateIndicator.className = "qiuwen-skeleton-state";
    this.stateIndicator.textContent = "空闲";
    this.skeletonEl.appendChild(this.stateIndicator);

    this.container.appendChild(this.skeletonEl);
  }

  /**
   * 无感切换到 3D 球体。
   *
   * 过渡效果：
   *   1. 骨架球 opacity → 0（0.3s）
   *   2. 3D Canvas opacity → 1（0.3s）
   *   3. 移除骨架球 DOM
   */
  private transitionTo3D(): void {
    if (!this.skeletonEl) return;

    // 淡出骨架
    this.skeletonEl.style.transition = "opacity 0.3s ease";
    this.skeletonEl.style.opacity = "0";

    setTimeout(() => {
      this.skeletonEl?.remove();
      this.skeletonEl = null;
    }, 300);
  }

  /**
   * 更新球体状态。
   * 同时更新骨架球（如果还在显示）和 3D 球体。
   */
  setState(state: BallState): void {
    // 更新 3D 球体
    this.ball3d?.setState(state);

    // 更新骨架球状态文字
    if (this.stateIndicator) {
      const stateTexts: Record<BallState, string> = {
        idle: "空闲",
        thinking: "思考中...",
        speaking: "说话中...",
        listening: "聆听中...",
        watching: "观察中...",
        sleeping: "休眠中",
        error: "出错了",
      };
      this.stateIndicator.textContent = stateTexts[state] || "";
    }

    // 更新骨架球颜色
    if (this.skeletonEl) {
      const stateColors: Record<BallState, string> = {
        idle: "linear-gradient(135deg, #4A90D9 0%, #6BA5E7 50%, #8CC4F0 100%)",
        thinking: "linear-gradient(135deg, #F0AD4E 0%, #F5C67A 50%, #FADA8E 100%)",
        speaking: "linear-gradient(135deg, #5CB85C 0%, #7ED17E 50%, #A0E8A0 100%)",
        listening: "linear-gradient(135deg, #5BC0DE 0%, #85D4E8 50%, #A8E4F0 100%)",
        watching: "linear-gradient(135deg, #4A90D9 0%, #6BA5E7 50%, #8CC4F0 100%)",
        sleeping: "linear-gradient(135deg, #7F8C9B 0%, #9BA8B5 50%, #B8C4CF 100%)",
        error: "linear-gradient(135deg, #EF4444 0%, #F87171 50%, #FCA5A5 100%)",
      };
      this.skeletonEl.style.background = stateColors[state] || stateColors.idle;
    }
  }

  /**
   * 设置口型张开比例。
   * 委托给 Ball3D 实例。
   */
  setMouthOpen(ratio: number): void {
    this.ball3d?.setMouthOpen(ratio);
  }

  /** 销毁所有资源。 */
  dispose(): void {
    this.ball3d?.dispose();
    this.skeletonEl?.remove();
  }
}
