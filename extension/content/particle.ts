/**
 * 求问 — 粒子动画模块
 * ====================
 *
 * 职责：
 *   - Canvas 粒子动画（从球体飞向目标元素）
 *   - 拖尾效果
 *   - 60fps requestAnimationFrame
 *
 * 从 highlight.ts 拆分而来。
 */

/** 颜色常量 */
const COLORS = {
  primaryRgb: "74, 144, 217",
};

/**
 * 粒子类。
 * 从起始位置飞向目标位置，带拖尾效果。
 */
export class Particle {
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  size: number;
  speed: number;
  opacity: number;
  trail: { x: number; y: number; opacity: number }[];

  constructor(startX: number, startY: number, targetX: number, targetY: number) {
    this.x = startX;
    this.y = startY;
    this.targetX = targetX;
    this.targetY = targetY;
    this.size = 2 + Math.random() * 3;
    this.speed = 0.02 + Math.random() * 0.03;
    this.opacity = 1;
    this.trail = [];
  }

  /** 更新位置。返回 true 表示已到达目标。 */
  update(): boolean {
    this.trail.push({ x: this.x, y: this.y, opacity: this.opacity });
    if (this.trail.length > 8) this.trail.shift();

    const dx = this.targetX - this.x;
    const dy = this.targetY - this.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 5) return true;

    this.x += dx * this.speed;
    this.y += dy * this.speed;
    this.speed = Math.min(this.speed + 0.001, 0.08);

    return false;
  }

  /** 绘制粒子和拖尾。 */
  draw(ctx: CanvasRenderingContext2D): void {
    // 拖尾
    for (let i = 0; i < this.trail.length; i++) {
      const t = this.trail[i];
      const alpha = (i / this.trail.length) * 0.5;
      ctx.beginPath();
      ctx.arc(t.x, t.y, this.size * 0.5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${COLORS.primaryRgb}, ${alpha})`;
      ctx.fill();
    }

    // 本体
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${COLORS.primaryRgb}, ${this.opacity})`;
    ctx.fill();

    // 发光
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size * 2, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${COLORS.primaryRgb}, 0.15)`;
    ctx.fill();
  }
}

/**
 * 粒子动画管理器。
 */
export class ParticleAnimator {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private animId: number | null = null;

  constructor(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D) {
    this.canvas = canvas;
    this.ctx = ctx;
  }

  /**
   * 启动粒子动画。
   * @param targetRect 目标元素矩形
   * @param particleCount 粒子数量
   */
  start(targetRect: DOMRect, particleCount: number = 12): void {
    const targetX = targetRect.left + targetRect.width / 2;
    const targetY = targetRect.top + targetRect.height / 2;
    const startX = window.innerWidth - 50;
    const startY = window.innerHeight / 2;

    const particles: Particle[] = [];
    for (let i = 0; i < particleCount; i++) {
      particles.push(new Particle(
        startX + (Math.random() - 0.5) * 40,
        startY + (Math.random() - 0.5) * 40,
        targetX + (Math.random() - 0.5) * 20,
        targetY + (Math.random() - 0.5) * 20,
      ));
    }

    this.stop();
    this.animate(particles);
  }

  /** 停止动画。 */
  stop(): void {
    if (this.animId) {
      cancelAnimationFrame(this.animId);
      this.animId = null;
    }
    this.clear();
  }

  private animate(particles: Particle[]): void {
    const dpr = window.devicePixelRatio || 1;
    const w = this.canvas.width / dpr;
    const h = this.canvas.height / dpr;

    const frame = () => {
      this.ctx.clearRect(0, 0, w, h);

      let allDone = true;
      for (const p of particles) {
        const done = p.update();
        p.draw(this.ctx);
        if (!done) allDone = false;
      }

      if (!allDone) {
        this.animId = requestAnimationFrame(frame);
      } else {
        this.clear();
      }
    };

    this.animId = requestAnimationFrame(frame);
  }

  private clear(): void {
    const dpr = window.devicePixelRatio || 1;
    this.ctx.clearRect(0, 0, this.canvas.width / dpr, this.canvas.height / dpr);
  }
}
