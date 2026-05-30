/**
 * 求问 — 3D 球体渲染（Three.js）
 * Phase 3 实现阶段，当前为骨架代码。
 */

import type { BallState } from "../common/types";

/**
 * 3D 球体管理器。
 * Phase 3 实现：使用 Three.js 渲染 6 种状态的 3D 球体。
 */
export class Ball3D {
  private container: HTMLElement;
  private state: BallState = "idle";

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async initialize(): Promise<void> {
    // TODO: Phase 3 实现
    // 1. 创建 Three.js 场景、相机、渲染器
    // 2. 创建球体几何体 + 材质
    // 3. 添加光照
    // 4. 启动动画循环
    console.log("[Ball3D] 初始化（骨架）");
  }

  setState(state: BallState): void {
    this.state = state;
    // TODO: Phase 3 实现 - 切换动画
    // idle: 缓慢旋转
    // thinking: 脉冲 + 颜色变化
    // speaking: 口型同步
    // listening: 麦克风动画
    // watching: 眼球跟踪
    // sleeping: 呼吸灯
    console.log("[Ball3D] 状态切换:", state);
  }

  setMouthOpen(ratio: number): void {
    // TODO: Phase 4 实现 - TTS 口型同步
  }

  dispose(): void {
    // 清理 Three.js 资源
    console.log("[Ball3D] 已销毁");
  }
}
