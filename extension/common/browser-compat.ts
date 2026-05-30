/**
 * 求问 — 浏览器兼容层
 * 封装 Chrome/Edge/Firefox 的 API 差异。
 *
 * 差异点：
 *   - 侧边栏：Chrome/Edge 用 sidePanel，Firefox 用 sidebar_action
 *   - 后台脚本：Chrome/Edge 用 service_worker，Firefox 用 background.scripts
 *   - 注入时机：Chrome/Edge document_start 稳定，Firefox 有时延迟
 */

// Firefox WebExtension API 类型声明
declare const browser: any;

// ---------------------------------------------------------------------------
// 浏览器类型检测
// ---------------------------------------------------------------------------

export type BrowserType = "chrome" | "edge" | "firefox" | "unknown";

export function getBrowserType(): BrowserType {
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("edg/")) return "edge";
  if (ua.includes("firefox/")) return "firefox";
  if (ua.includes("chrome/")) return "chrome";
  return "unknown";
}

/** 是否为 Chromium 内核（Chrome/Edge） */
export function isChromium(): boolean {
  const type = getBrowserType();
  return type === "chrome" || type === "edge";
}

// ---------------------------------------------------------------------------
// 侧边栏 API
// ---------------------------------------------------------------------------

export interface SidebarAPI {
  open(): Promise<void>;
  close(): Promise<void>;
  toggle(): Promise<void>;
}

export function getSidebarAPI(): SidebarAPI {
  const browser = getBrowserType();

  if (browser === "firefox") {
    // Firefox 使用 sidebar_action（MV2/MV3 均支持）
    const sidebarAction = (globalThis as any).browser?.sidebarAction || (chrome as any).sidebarAction;
    if (sidebarAction) {
      return {
        async open() {
          await sidebarAction.open();
        },
        async close() {
          await sidebarAction.close();
        },
        async toggle() {
          // Firefox 没有原生 toggle，通过 open/close 实现
          // sidebarAction.isOpen() 在某些版本不可用
          try {
            const isOpen = await sidebarAction.isOpen?.({});
            if (isOpen) {
              await sidebarAction.close();
            } else {
              await sidebarAction.open();
            }
          } catch {
            await sidebarAction.open();
          }
        },
      };
    }
  }

  // Chrome/Edge 使用 sidePanel
  const sidePanel = (chrome as any).sidePanel;
  if (sidePanel) {
    return {
      async open() {
        try {
          await sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
        } catch (e) {
          console.warn("[求问] sidePanel.open failed:", e);
        }
      },
      async close() {
        // Chrome sidePanel 没有直接 close API
      },
      async toggle() {
        try {
          await sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
        } catch (e) {
          console.warn("[求问] sidePanel.toggle failed:", e);
        }
      },
    };
  }

  // 降级：popup 模式
  return {
    async open() {
      console.warn("[求问] 无侧边栏 API，使用 popup 模式");
    },
    async close() {},
    async toggle() {},
  };
}

// ---------------------------------------------------------------------------
// 截图 API
// ---------------------------------------------------------------------------

export async function captureVisibleTab(): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab({ format: "png" }, (dataUrl) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(dataUrl);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Content Script 注入时机
// ---------------------------------------------------------------------------

export function injectAtStart(fn: () => void): void {
  const browser = getBrowserType();

  if (browser === "firefox") {
    // Firefox 的 document_start 有时延迟，降级为 DOMContentLoaded
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  } else {
    // Chrome/Edge: 直接执行
    fn();
  }
}

// ---------------------------------------------------------------------------
// 存储 API
// ---------------------------------------------------------------------------

/**
 * 跨浏览器存储 API。
 * Chrome 用 chrome.storage.local
 * Firefox 用 browser.storage.local（Promise 化）
 */
export function getStorageArea(): any {
  if (typeof browser !== "undefined" && browser.storage) {
    return browser.storage.local;
  }
  return chrome.storage.local;
}

/**
 * 跨浏览器 storage.get（Promise 化）。
 */
export async function storageGet(keys: string[]): Promise<Record<string, any>> {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, (data) => {
      resolve(data as Record<string, any>);
    });
  });
}

/**
 * 跨浏览器 storage.set（Promise 化）。
 */
export async function storageSet(items: Record<string, any>): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set(items, resolve);
  });
}

// ---------------------------------------------------------------------------
// 运行时消息
// ---------------------------------------------------------------------------

/**
 * 跨浏览器 runtime.sendMessage。
 * Firefox 的 browser.runtime.sendMessage 返回 Promise。
 */
export function sendMessage(msg: any): Promise<any> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (response) => {
      resolve(response);
    });
  });
}
