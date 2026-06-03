/**
 * 求问 — 新手引导流程
 * ====================
 *
 * 职责：
 *   1. 首次使用引导
 *   2. 系统状态检测
 *   3. 模型选择
 *   4. 功能演示
 *
 * 流程：
 *   Step 1: 欢迎 + 系统检测
 *   Step 2: 选择推理模式
 *   Step 3: 试一试
 */

import { API_BASE, STORAGE_KEYS } from "../common/constants";
import { getDiagnostics, renderDiagnosticReport, type DiagnosticReport } from "./diagnostics";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------
const WELCOME_STORAGE_KEY = "qiuwen_welcome_completed";

// ---------------------------------------------------------------------------
// 引导类
// ---------------------------------------------------------------------------
class WelcomeFlow {
  private container: HTMLElement;
  private step: number = 0;
  private diagnosticReport: DiagnosticReport | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  /**
   * 检查是否需要显示引导
   */
  async shouldShow(): Promise<boolean> {
    return new Promise((resolve) => {
      chrome.storage.local.get(WELCOME_STORAGE_KEY, (data) => {
        resolve(!data[WELCOME_STORAGE_KEY]);
      });
    });
  }

  /**
   * 启动引导流程
   */
  async start(): Promise<void> {
    const shouldShow = await this.shouldShow();
    if (!shouldShow) return;

    this.step = 1;
    await this.showStep1();
  }

  // -----------------------------------------------------------------------
  // Step 1: 欢迎 + 系统检测
  // -----------------------------------------------------------------------
  private async showStep1(): Promise<void> {
    this.container.innerHTML = "";
    this.container.className = "welcome-container";

    // 标题
    const title = document.createElement("h2");
    title.className = "welcome-title";
    title.textContent = "👋 欢迎使用求问";
    this.container.appendChild(title);

    const subtitle = document.createElement("p");
    subtitle.className = "welcome-subtitle";
    subtitle.textContent = "让我们检查一下系统状态";
    this.container.appendChild(subtitle);

    // 诊断区域
    const diagnosticContainer = document.createElement("div");
    diagnosticContainer.className = "welcome-diagnostic";
    this.container.appendChild(diagnosticContainer);

    // 运行诊断
    const diagnostics = getDiagnostics();
    this.diagnosticReport = await diagnostics.runFullCheck();
    renderDiagnosticReport(diagnosticContainer, this.diagnosticReport);

    // 下一步按钮
    const nextBtn = document.createElement("button");
    nextBtn.className = "welcome-btn welcome-btn-primary";
    nextBtn.textContent = "下一步";
    nextBtn.addEventListener("click", () => this.showStep2());
    this.container.appendChild(nextBtn);
  }

  // -----------------------------------------------------------------------
  // Step 2: 选择推理模式
  // -----------------------------------------------------------------------
  private async showStep2(): Promise<void> {
    this.container.innerHTML = "";

    const title = document.createElement("h2");
    title.className = "welcome-title";
    title.textContent = "选择推理模式";
    this.container.appendChild(title);

    const subtitle = document.createElement("p");
    subtitle.className = "welcome-subtitle";
    subtitle.textContent = "选择 AI 模型运行方式";
    this.container.appendChild(subtitle);

    // 模式选项
    const options = document.createElement("div");
    options.className = "welcome-options";

    const modes = [
      {
        value: "local",
        icon: "🏠",
        title: "本地模式（推荐）",
        desc: "数据不出本机，隐私安全",
        requirement: "需要: Ollama + 8GB 显存",
        recommended: true,
      },
      {
        value: "cloud",
        icon: "☁️",
        title: "云端模式",
        desc: "更强的 AI 能力",
        requirement: "需要: API Key",
        recommended: false,
      },
      {
        value: "hybrid",
        icon: "🔄",
        title: "混合模式",
        desc: "本地优先，自动降级云端",
        requirement: "需要: Ollama 或 API Key",
        recommended: false,
      },
    ];

    let selectedMode = "local";

    for (const mode of modes) {
      const card = document.createElement("div");
      card.className = `welcome-option-card ${mode.recommended ? "selected" : ""}`;
      card.dataset.mode = mode.value;

      card.innerHTML = `
        <div class="option-header">
          <span class="option-icon">${mode.icon}</span>
          <span class="option-title">${mode.title}</span>
          ${mode.recommended ? '<span class="option-badge">推荐</span>' : ""}
        </div>
        <div class="option-desc">${mode.desc}</div>
        <div class="option-requirement">${mode.requirement}</div>
      `;

      card.addEventListener("click", () => {
        options.querySelectorAll(".welcome-option-card").forEach((c) => {
          c.classList.remove("selected");
        });
        card.classList.add("selected");
        selectedMode = mode.value;
      });

      options.appendChild(card);
    }

    this.container.appendChild(options);

    // 按钮区域
    const btnGroup = document.createElement("div");
    btnGroup.className = "welcome-btn-group";

    const backBtn = document.createElement("button");
    backBtn.className = "welcome-btn welcome-btn-secondary";
    backBtn.textContent = "上一步";
    backBtn.addEventListener("click", () => this.showStep1());

    const nextBtn = document.createElement("button");
    nextBtn.className = "welcome-btn welcome-btn-primary";
    nextBtn.textContent = "下一步";
    nextBtn.addEventListener("click", async () => {
      // 保存模式选择
      chrome.storage.sync.set({ modelStrategy: selectedMode });
      await this.showStep3();
    });

    btnGroup.appendChild(backBtn);
    btnGroup.appendChild(nextBtn);
    this.container.appendChild(btnGroup);
  }

  // -----------------------------------------------------------------------
  // Step 3: 试一试
  // -----------------------------------------------------------------------
  private async showStep3(): Promise<void> {
    this.container.innerHTML = "";

    const title = document.createElement("h2");
    title.className = "welcome-title";
    title.textContent = "试一试";
    this.container.appendChild(title);

    const subtitle = document.createElement("p");
    subtitle.className = "welcome-subtitle";
    subtitle.textContent = "让我们体验一下求问的功能";
    this.container.appendChild(subtitle);

    // 演示区域
    const demoArea = document.createElement("div");
    demoArea.className = "welcome-demo";

    const demoQuestion = document.createElement("div");
    demoQuestion.className = "demo-question";

    const demoLabel = document.createElement("span");
    demoLabel.textContent = "试试问：";

    const demoBtn = document.createElement("button");
    demoBtn.className = "demo-btn";
    demoBtn.textContent = "帮我找找创建项目的位置";
    demoBtn.addEventListener("click", () => {
      // 发送演示消息
      chrome.runtime.sendMessage({
        type: "qiuwen:send_message",
        text: "帮我找找创建项目的位置",
      });
      this.finishWelcome();
    });

    demoQuestion.appendChild(demoLabel);
    demoQuestion.appendChild(demoBtn);
    demoArea.appendChild(demoQuestion);

    const demoTip = document.createElement("div");
    demoTip.className = "demo-tip";
    demoTip.textContent = "💡 求问会在页面上高亮目标位置";
    demoArea.appendChild(demoTip);

    this.container.appendChild(demoArea);

    // 按钮区域
    const btnGroup = document.createElement("div");
    btnGroup.className = "welcome-btn-group";

    const backBtn = document.createElement("button");
    backBtn.className = "welcome-btn welcome-btn-secondary";
    backBtn.textContent = "上一步";
    backBtn.addEventListener("click", () => this.showStep2());

    const finishBtn = document.createElement("button");
    finishBtn.className = "welcome-btn welcome-btn-primary";
    finishBtn.textContent = "开始使用";
    finishBtn.addEventListener("click", () => this.finishWelcome());

    btnGroup.appendChild(backBtn);
    btnGroup.appendChild(finishBtn);
    this.container.appendChild(btnGroup);
  }

  // -----------------------------------------------------------------------
  // 完成引导
  // -----------------------------------------------------------------------
  private async finishWelcome(): Promise<void> {
    // 标记引导完成
    chrome.storage.local.set({ [WELCOME_STORAGE_KEY]: true });

    // 隐藏引导界面
    this.container.innerHTML = "";
    this.container.className = "";

    // 触发事件通知其他组件
    chrome.runtime.sendMessage({ type: "qiuwen:welcome_completed" });
  }
}

// ---------------------------------------------------------------------------
// 样式注入
// ---------------------------------------------------------------------------
function injectWelcomeStyles(): void {
  if (document.getElementById("qiuwen-welcome-styles")) return;

  const style = document.createElement("style");
  style.id = "qiuwen-welcome-styles";
  style.textContent = `
    .welcome-container {
      padding: 24px;
      max-width: 400px;
      margin: 0 auto;
    }

    .welcome-title {
      font-size: 20px;
      font-weight: 600;
      text-align: center;
      margin-bottom: 8px;
      color: #1a1a2e;
    }

    .welcome-subtitle {
      font-size: 14px;
      text-align: center;
      color: #6c757d;
      margin-bottom: 24px;
    }

    .welcome-diagnostic {
      margin-bottom: 24px;
    }

    .welcome-options {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 24px;
    }

    .welcome-option-card {
      padding: 16px;
      border: 2px solid #e9ecef;
      border-radius: 12px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .welcome-option-card:hover {
      border-color: #4A90D9;
      background: #f8f9ff;
    }

    .welcome-option-card.selected {
      border-color: #4A90D9;
      background: #e8f0fe;
    }

    .option-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }

    .option-icon {
      font-size: 20px;
    }

    .option-title {
      font-size: 15px;
      font-weight: 600;
      color: #1a1a2e;
    }

    .option-badge {
      font-size: 11px;
      background: #4A90D9;
      color: white;
      padding: 2px 6px;
      border-radius: 4px;
      margin-left: auto;
    }

    .option-desc {
      font-size: 13px;
      color: #495057;
      margin-bottom: 4px;
    }

    .option-requirement {
      font-size: 12px;
      color: #6c757d;
    }

    .welcome-btn-group {
      display: flex;
      gap: 12px;
    }

    .welcome-btn {
      flex: 1;
      padding: 12px 16px;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }

    .welcome-btn-primary {
      background: #4A90D9;
      color: white;
    }

    .welcome-btn-primary:hover {
      background: #3a7bc8;
    }

    .welcome-btn-secondary {
      background: #e9ecef;
      color: #495057;
    }

    .welcome-btn-secondary:hover {
      background: #dee2e6;
    }

    .welcome-demo {
      background: #f8f9fa;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 24px;
      text-align: center;
    }

    .demo-question {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-bottom: 12px;
    }

    .demo-btn {
      padding: 8px 16px;
      background: #4A90D9;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      transition: background 0.2s;
    }

    .demo-btn:hover {
      background: #3a7bc8;
    }

    .demo-tip {
      font-size: 13px;
      color: #6c757d;
    }

    /* 诊断样式 */
    .diagnostic-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid #e9ecef;
    }

    .diagnostic-status {
      font-size: 20px;
    }

    .diagnostic-status-text {
      font-size: 16px;
      font-weight: 600;
      color: #1a1a2e;
    }

    .diagnostic-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .diagnostic-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: #f8f9fa;
      border-radius: 8px;
    }

    .diagnostic-item-icon {
      font-size: 16px;
    }

    .diagnostic-item-label {
      font-size: 14px;
      font-weight: 500;
      color: #1a1a2e;
      min-width: 80px;
    }

    .diagnostic-item-message {
      font-size: 13px;
      color: #6c757d;
      flex: 1;
    }

    .diagnostic-fix-btn {
      padding: 4px 10px;
      background: #4A90D9;
      color: white;
      border: none;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
      transition: background 0.2s;
    }

    .diagnostic-fix-btn:hover {
      background: #3a7bc8;
    }

    .diagnostic-fix-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .diagnostic-fixes {
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid #e9ecef;
    }

    .diagnostic-fixes-title {
      font-size: 14px;
      font-weight: 600;
      color: #1a1a2e;
      margin-bottom: 8px;
    }

    .diagnostic-fix-item {
      display: flex;
      gap: 8px;
      padding: 6px 0;
      font-size: 13px;
    }

    .fix-label {
      font-weight: 500;
      color: #495057;
    }

    .fix-desc {
      color: #6c757d;
    }
  `;

  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// 全局实例
// ---------------------------------------------------------------------------
let welcomeFlow: WelcomeFlow | null = null;

export function getWelcomeFlow(): WelcomeFlow | null {
  return welcomeFlow;
}

export function initWelcomeFlow(container: HTMLElement): WelcomeFlow {
  injectWelcomeStyles();
  welcomeFlow = new WelcomeFlow(container);
  return welcomeFlow;
}
