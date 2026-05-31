/**
 * 求问 — 3D 球体渲染器 (Three.js)
 * ===================================
 *
 * 职责：
 *   1. 使用 Three.js 渲染蓝白渐变 3D 球体
 *   2. 支持 6 种状态动画：idle / thinking / speaking / listening / watching / sleeping
 *   3. Shadow DOM 样式隔离（防止页面 CSS 污染）
 *   4. 帧率控制：IDLE 60fps / WATCHING 30fps / SLEEPING 10fps
 *   5. 口型同步接口（Phase 4 TTS 使用）
 *
 * 性能目标：
 *   - 骨架球出现 < 50ms（CSS 2D，不依赖 Three.js）
 *   - 3D 球加载 < 1500ms（Three.js 异步加载）
 *   - IDLE 内存 < 30MB
 *
 * 球体外观：
 *   - 蓝白渐变材质（主色 #4A90D9）
 *   - 柔和光照（环境光 + 方向光）
 *   - 缓慢旋转（idle 状态）
 *   - 脉冲缩放（thinking 状态）
 */

import type { BallState } from "../common/types";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/** 球体颜色 */
const BALL_COLORS = {
  primary: 0x4a90d9,     // 蓝色
  secondary: 0x6ba5e7,   // 浅蓝
  glow: 0x8cc4f0,        // 光晕
  sleeping: 0x7f8c9b,    // 灰蓝（休眠）
  thinking: 0xf0ad4e,    // 橙色（思考）
  speaking: 0x5cb85c,    // 绿色（说话）
  listening: 0x5bc0de,   // 青色（监听）
  error: 0xd9534f,       // 红色（错误）
};

/** 帧率配置 */
const FPS: Record<string, number> = {
  idle: 60,
  thinking: 60,
  speaking: 60,
  listening: 30,
  watching: 30,
  sleeping: 10,
  error: 60,
};

// ---------------------------------------------------------------------------
// Ball3D 类
// ---------------------------------------------------------------------------

export class Ball3D {
  private container: HTMLElement;
  private shadowRoot: ShadowRoot | null = null;
  private canvas: HTMLCanvasElement | null = null;

  // Three.js 核心对象（延迟加载）
  private scene: any = null;
  private camera: any = null;
  private renderer: any = null;
  private ballMesh: any = null;
  private ambientLight: any = null;
  private directionalLight: any = null;

  // 动画状态
  private state: BallState = "idle";
  private animationId: number | null = null;
  private lastFrameTime: number = 0;
  private frameInterval: number = 1000 / 60; // 默认 60fps
  private rotationSpeed: number = 0.005;
  private pulsePhase: number = 0;
  private mouthOpenRatio: number = 0; // 口型同步

  // Three.js 加载状态
  private threeLoaded: boolean = false;
  private loadingPromise: Promise<void> | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  // -----------------------------------------------------------------------
  // 初始化
  // -----------------------------------------------------------------------

  /**
   * 初始化球体。
   *
   * 流程：
   *   1. 创建 Shadow DOM（样式隔离）
   *   2. 创建 Canvas
   *   3. 异步加载 Three.js（不阻塞骨架球显示）
   *   4. 加载完成后创建 3D 场景并启动动画
   */
  async initialize(): Promise<void> {
    // 创建 Shadow DOM
    this.shadowRoot = this.container.attachShadow({ mode: "closed" });

    // 注入样式
    const style = document.createElement("style");
    style.textContent = `
      :host {
        display: block;
        width: 100%;
        height: 100%;
        position: relative;
      }
      canvas {
        display: block;
        width: 100%;
        height: 100%;
      }
    `;
    this.shadowRoot.appendChild(style);

    // 创建 Canvas
    this.canvas = document.createElement("canvas");
    this.canvas.width = 200;
    this.canvas.height = 200;
    this.shadowRoot.appendChild(this.canvas);

    // 异步加载 Three.js
    this.loadingPromise = this.loadThreeJS();
    await this.loadingPromise;
  }

  /**
   * 异步加载 Three.js。
   *
   * 使用动态 import 加载，不阻塞骨架球的显示。
   * 加载完成后创建 3D 场景。
   */
  private async loadThreeJS(): Promise<void> {
    try {
      // 按需引入（tree-shaking 优化，不加载整个 three 包）
      const { Scene, PerspectiveCamera, WebGLRenderer, SphereGeometry, MeshPhongMaterial, AmbientLight, DirectionalLight, Mesh } = await import("three");

      // 创建场景
      this.scene = new Scene();

      // 创建相机
      this.camera = new PerspectiveCamera(45, 1, 0.1, 100);
      this.camera.position.z = 3;

      // 创建渲染器
      this.renderer = new WebGLRenderer({
        canvas: this.canvas!,
        alpha: true,
        antialias: true,
      });
      this.renderer.setSize(200, 200);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

      // 创建球体
      const geometry = new SphereGeometry(1, 32, 32);
      const material = new MeshPhongMaterial({
        color: BALL_COLORS.primary,
        emissive: BALL_COLORS.secondary,
        emissiveIntensity: 0.3,
        shininess: 80,
        transparent: true,
        opacity: 0.9,
      });
      this.ballMesh = new Mesh(geometry, material);
      this.scene.add(this.ballMesh);

      // 光照
      this.ambientLight = new AmbientLight(0xffffff, 0.6);
      this.scene.add(this.ambientLight);

      this.directionalLight = new DirectionalLight(0xffffff, 0.8);
      this.directionalLight.position.set(2, 2, 3);
      this.scene.add(this.directionalLight);

      this.threeLoaded = true;
      this.startAnimation();
      console.log("[Ball3D] Three.js 加载完成");
    } catch (e) {
      console.warn("[Ball3D] Three.js 加载失败，保留 2D 骨架", e);
    }
  }

  // -----------------------------------------------------------------------
  // 状态管理
  // -----------------------------------------------------------------------

  /**
   * 设置球体状态。
   *
   * 状态动画：
   *   idle:      缓慢旋转，蓝色
   *   thinking:  脉冲缩放 + 橙色
   *   speaking:  口型动画 + 绿色
   *   listening: 轻微抖动 + 青色
   *   watching:  眼球跟踪（球体微转）+ 蓝色
   *   sleeping:  呼吸灯（缓慢明暗）+ 灰蓝
   */
  setState(state: BallState): void {
    this.state = state;

    if (!this.threeLoaded || !this.ballMesh) return;

    // 更新帧率
    this.frameInterval = 1000 / (FPS[state] || 30);

    // 更新颜色
    const material = this.ballMesh.material;
    switch (state) {
      case "idle":
        material.color.setHex(BALL_COLORS.primary);
        material.emissive.setHex(BALL_COLORS.secondary);
        this.rotationSpeed = 0.005;
        break;
      case "thinking":
        material.color.setHex(BALL_COLORS.thinking);
        material.emissive.setHex(BALL_COLORS.thinking);
        this.rotationSpeed = 0.02;
        break;
      case "speaking":
        material.color.setHex(BALL_COLORS.speaking);
        material.emissive.setHex(BALL_COLORS.speaking);
        this.rotationSpeed = 0.01;
        break;
      case "listening":
        material.color.setHex(BALL_COLORS.listening);
        material.emissive.setHex(BALL_COLORS.listening);
        this.rotationSpeed = 0.008;
        break;
      case "watching":
        material.color.setHex(BALL_COLORS.primary);
        material.emissive.setHex(BALL_COLORS.glow);
        this.rotationSpeed = 0.003;
        break;
      case "sleeping":
        material.color.setHex(BALL_COLORS.sleeping);
        material.emissive.setHex(BALL_COLORS.sleeping);
        this.rotationSpeed = 0.001;
        break;
      case "error":
        material.color.setHex(BALL_COLORS.error);
        material.emissive.setHex(BALL_COLORS.error);
        this.rotationSpeed = 0.03;
        break;
    }
  }

  /**
   * 设置口型张开比例（0-1）。
   *
   * Phase 4 TTS 使用：根据音频振幅实时更新口型。
   * 实现方式：缩放球体 Y 轴模拟嘴巴张合。
   */
  setMouthOpen(ratio: number): void {
    this.mouthOpenRatio = Math.max(0, Math.min(1, ratio));
  }

  // -----------------------------------------------------------------------
  // 动画循环
  // -----------------------------------------------------------------------

  /** 启动动画循环。 */
  private startAnimation(): void {
    if (this.animationId) return;
    this.lastFrameTime = performance.now();
    this.animate(this.lastFrameTime);
  }

  /** 停止动画循环。 */
  private stopAnimation(): void {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  /**
   * 动画帧回调。
   *
   * 帧率控制：使用 setInterval 思路，只在需要时渲染。
   * 每帧根据 state 执行不同的动画逻辑。
   */
  private animate(currentTime: number): void {
    this.animationId = requestAnimationFrame((t) => this.animate(t));

    // 帧率控制
    const elapsed = currentTime - this.lastFrameTime;
    if (elapsed < this.frameInterval) return;
    this.lastFrameTime = currentTime - (elapsed % this.frameInterval);

    if (!this.threeLoaded || !this.ballMesh) return;

    // 根据状态执行动画
    switch (this.state) {
      case "idle":
        this.animateIdle();
        break;
      case "thinking":
        this.animateThinking();
        break;
      case "speaking":
        this.animateSpeaking();
        break;
      case "listening":
        this.animateListening();
        break;
      case "watching":
        this.animateWatching();
        break;
      case "sleeping":
        this.animateSleeping();
        break;
    }

    // 渲染
    this.renderer.render(this.scene, this.camera);
  }

  /** 空闲动画：缓慢旋转。 */
  private animateIdle(): void {
    this.ballMesh.rotation.y += this.rotationSpeed;
    this.ballMesh.rotation.x += this.rotationSpeed * 0.3;
    // 恢复缩放
    this.ballMesh.scale.lerp({ x: 1, y: 1, z: 1 } as any, 0.1);
  }

  /** 思考动画：脉冲缩放。 */
  private animateThinking(): void {
    this.pulsePhase += 0.05;
    const scale = 1 + Math.sin(this.pulsePhase) * 0.08;
    this.ballMesh.scale.set(scale, scale, scale);
    this.ballMesh.rotation.y += this.rotationSpeed;
  }

  /** 说话动画：口型同步（Y 轴缩放）。 */
  private animateSpeaking(): void {
    this.ballMesh.rotation.y += this.rotationSpeed;
    // 口型同步：Y 轴轻微缩放
    const mouthScale = 1 + this.mouthOpenRatio * 0.15;
    this.ballMesh.scale.set(1, mouthScale, 1);
  }

  /** 监听动画：轻微抖动。 */
  private animateListening(): void {
    this.pulsePhase += 0.08;
    const jitterX = Math.sin(this.pulsePhase) * 0.02;
    const jitterY = Math.cos(this.pulsePhase * 1.3) * 0.02;
    this.ballMesh.rotation.x += jitterX;
    this.ballMesh.rotation.y += jitterY;
  }

  /** 观察动画：微转（模拟眼球跟踪）。 */
  private animateWatching(): void {
    this.ballMesh.rotation.y += this.rotationSpeed;
  }

  /** 休眠动画：呼吸灯（透明度变化）。 */
  private animateSleeping(): void {
    this.pulsePhase += 0.02;
    const opacity = 0.6 + Math.sin(this.pulsePhase) * 0.2;
    this.ballMesh.material.opacity = opacity;
    this.ballMesh.rotation.y += this.rotationSpeed;
  }

  // -----------------------------------------------------------------------
  // 销毁
  // -----------------------------------------------------------------------

  /** 清理 Three.js 资源。 */
  dispose(): void {
    this.stopAnimation();
    if (this.renderer) {
      this.renderer.dispose();
    }
    if (this.ballMesh) {
      this.ballMesh.geometry.dispose();
      this.ballMesh.material.dispose();
    }
    console.log("[Ball3D] 已销毁");
  }
}
