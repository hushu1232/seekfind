/**
 * 求问 — 快捷键系统
 * ==================
 *
 * 职责：
 *   1. 全局快捷键监听
 *   2. 支持自定义快捷键
 *   3. 快捷键冲突检测
 *
 * 默认快捷键：
 *   Ctrl+Shift+Q  → 唤出/隐藏侧边栏
 *   Ctrl+Shift+H  → 高亮上一个目标
 *   Ctrl+Shift+R  → 重复上一个指引
 *   Escape        → 清除所有高亮
 *   Ctrl+Shift+M  → 开启/关闭语音
 */

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------
export interface ShortcutConfig {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: string;
  description: string;
}

interface ShortcutState {
  config: ShortcutConfig;
  lastTriggered: number;
}

// ---------------------------------------------------------------------------
// 默认快捷键
// ---------------------------------------------------------------------------
export const DEFAULT_SHORTCUTS: ShortcutConfig[] = [
  {
    key: "Q",
    ctrl: true,
    shift: true,
    action: "toggleSidebar",
    description: "唤出/隐藏侧边栏",
  },
  {
    key: "H",
    ctrl: true,
    shift: true,
    action: "highlightLast",
    description: "高亮上一个目标",
  },
  {
    key: "R",
    ctrl: true,
    shift: true,
    action: "repeatLastGuide",
    description: "重复上一个指引",
  },
  {
    key: "Escape",
    action: "clearHighlights",
    description: "清除所有高亮",
  },
  {
    key: "M",
    ctrl: true,
    shift: true,
    action: "toggleMicrophone",
    description: "开启/关闭语音",
  },
];

// ---------------------------------------------------------------------------
// 快捷键管理器
// ---------------------------------------------------------------------------
class ShortcutManager {
  private shortcuts: Map<string, ShortcutState> = new Map();
  private enabled: boolean = true;
  private lastHighlightSelector: string | null = null;
  private lastGuideSteps: any[] | null = null;

  constructor() {
    this.loadShortcuts();
    this.bindEvents();
    this.listenForUpdates();
  }

  // -----------------------------------------------------------------------
  // 加载快捷键配置
  // -----------------------------------------------------------------------
  private loadShortcuts(): void {
    chrome.storage.sync.get("shortcuts", (result) => {
      const saved: ShortcutConfig[] = result.shortcuts || DEFAULT_SHORTCUTS;
      this.registerShortcuts(saved);
    });
  }

  private registerShortcuts(configs: ShortcutConfig[]): void {
    this.shortcuts.clear();
    configs.forEach((config) => {
      const key = this.generateKey(config);
      this.shortcuts.set(key, {
        config,
        lastTriggered: 0,
      });
    });
  }

  // -----------------------------------------------------------------------
  // 生成快捷键标识
  // -----------------------------------------------------------------------
  private generateKey(config: ShortcutConfig): string {
    const parts: string[] = [];
    if (config.ctrl) parts.push("Ctrl");
    if (config.shift) parts.push("Shift");
    if (config.alt) parts.push("Alt");
    parts.push(config.key.toUpperCase());
    return parts.join("+");
  }

  private generateKeyFromEvent(e: KeyboardEvent): string {
    const parts: string[] = [];
    if (e.ctrlKey || e.metaKey) parts.push("Ctrl");
    if (e.shiftKey) parts.push("Shift");
    if (e.altKey) parts.push("Alt");
    parts.push(e.key.toUpperCase());
    return parts.join("+");
  }

  // -----------------------------------------------------------------------
  // 事件绑定
  // -----------------------------------------------------------------------
  private bindEvents(): void {
    document.addEventListener("keydown", (e) => {
      if (!this.enabled) return;

      // 忽略输入框内的快捷键
      if (this.isInputElement(e.target as HTMLElement)) {
        // 只允许 Escape 在输入框内生效
        if (e.key !== "Escape") return;
      }

      const key = this.generateKeyFromEvent(e);
      const state = this.shortcuts.get(key);

      if (state) {
        // 防抖：500ms 内不重复触发
        const now = Date.now();
        if (now - state.lastTriggered < 500) return;

        e.preventDefault();
        e.stopPropagation();
        state.lastTriggered = now;

        this.executeAction(state.config.action);
      }
    });
  }

  private isInputElement(el: HTMLElement): boolean {
    if (!el) return false;
    const tagName = el.tagName.toLowerCase();
    return (
      tagName === "input" ||
      tagName === "textarea" ||
      tagName === "select" ||
      el.isContentEditable
    );
  }

  // -----------------------------------------------------------------------
  // 监听配置更新
  // -----------------------------------------------------------------------
  private listenForUpdates(): void {
    chrome.storage.onChanged.addListener((changes) => {
      if (changes.shortcuts) {
        const newShortcuts: ShortcutConfig[] = changes.shortcuts.newValue;
        if (newShortcuts) {
          this.registerShortcuts(newShortcuts);
        }
      }
    });
  }

  // -----------------------------------------------------------------------
  // 执行动作
  // -----------------------------------------------------------------------
  private executeAction(action: string): void {
    switch (action) {
      case "toggleSidebar":
        this.toggleSidebar();
        break;
      case "highlightLast":
        this.highlightLast();
        break;
      case "repeatLastGuide":
        this.repeatLastGuide();
        break;
      case "clearHighlights":
        this.clearHighlights();
        break;
      case "toggleMicrophone":
        this.toggleMicrophone();
        break;
      default:
        console.warn("[求问] 未知快捷键动作:", action);
    }
  }

  // -----------------------------------------------------------------------
  // 动作实现
  // -----------------------------------------------------------------------
  private toggleSidebar(): void {
    chrome.runtime.sendMessage({ type: "qiuwen:toggle_sidebar" });
  }

  private highlightLast(): void {
    if (this.lastHighlightSelector) {
      chrome.runtime.sendMessage({
        type: "qiuwen:highlight",
        payload: {
          selector: this.lastHighlightSelector,
          description: "上一个目标",
          order: 1,
          style: "spotlight",
        },
      });
    }
  }

  private repeatLastGuide(): void {
    if (this.lastGuideSteps) {
      chrome.runtime.sendMessage({
        type: "qiuwen:repeat_guide",
        steps: this.lastGuideSteps,
      });
    }
  }

  private clearHighlights(): void {
    chrome.runtime.sendMessage({ type: "qiuwen:clear_highlight" });
    chrome.runtime.sendMessage({ type: "qiuwen:clear_spotlight" });
  }

  private toggleMicrophone(): void {
    chrome.runtime.sendMessage({ type: "qiuwen:toggle_microphone" });
  }

  // -----------------------------------------------------------------------
  // 外部接口
  // -----------------------------------------------------------------------
  public setLastHighlight(selector: string): void {
    this.lastHighlightSelector = selector;
  }

  public setLastGuideSteps(steps: any[]): void {
    this.lastGuideSteps = steps;
  }

  public enable(): void {
    this.enabled = true;
  }

  public disable(): void {
    this.enabled = false;
  }

  public isEnabled(): boolean {
    return this.enabled;
  }

  // -----------------------------------------------------------------------
  // 获取当前配置（用于设置面板）
  // -----------------------------------------------------------------------
  public getShortcuts(): ShortcutConfig[] {
    return Array.from(this.shortcuts.values()).map((s) => s.config);
  }

  public updateShortcut(action: string, newConfig: Partial<ShortcutConfig>): void {
    const shortcuts = this.getShortcuts();
    const index = shortcuts.findIndex((s) => s.action === action);
    if (index >= 0) {
      shortcuts[index] = { ...shortcuts[index], ...newConfig };
      chrome.storage.sync.set({ shortcuts });
      this.registerShortcuts(shortcuts);
    }
  }

  public resetToDefault(): void {
    chrome.storage.sync.set({ shortcuts: DEFAULT_SHORTCUTS });
    this.registerShortcuts(DEFAULT_SHORTCUTS);
  }
}

// ---------------------------------------------------------------------------
// 全局单例
// ---------------------------------------------------------------------------
let shortcutManager: ShortcutManager | null = null;

export function getShortcutManager(): ShortcutManager {
  if (!shortcutManager) {
    shortcutManager = new ShortcutManager();
  }
  return shortcutManager;
}

// ---------------------------------------------------------------------------
// 格式化快捷键显示
// ---------------------------------------------------------------------------
export function formatShortcutKey(config: ShortcutConfig): string {
  const parts: string[] = [];
  if (config.ctrl) parts.push("Ctrl");
  if (config.shift) parts.push("Shift");
  if (config.alt) parts.push("Alt");

  // 特殊键名映射
  const keyMap: Record<string, string> = {
    Escape: "Esc",
    ArrowUp: "↑",
    ArrowDown: "↓",
    ArrowLeft: "←",
    ArrowRight: "→",
    " ": "Space",
  };

  parts.push(keyMap[config.key] || config.key);
  return parts.join(" + ");
}

// ---------------------------------------------------------------------------
// 检测快捷键冲突
// ---------------------------------------------------------------------------
export function detectShortcutConflict(
  config: ShortcutConfig,
  existing: ShortcutConfig[]
): ShortcutConfig | null {
  const key = [
    config.ctrl ? "Ctrl" : "",
    config.shift ? "Shift" : "",
    config.alt ? "Alt" : "",
    config.key.toUpperCase(),
  ]
    .filter(Boolean)
    .join("+");

  return existing.find((s) => {
    const existingKey = [
      s.ctrl ? "Ctrl" : "",
      s.shift ? "Shift" : "",
      s.alt ? "Alt" : "",
      s.key.toUpperCase(),
    ]
      .filter(Boolean)
      .join("+");
    return existingKey === key && s.action !== config.action;
  }) || null;
}
