/**
 * 求问 — 浏览器兼容层
 * 封装 Chrome/Edge/Firefox 的 API 差异。
 */

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
    // Firefox 使用 sidebar_action
    return {
      async open() {
        await (chrome as any).sidebarAction.open();
      },
      async close() {
        await (chrome as any).sidebarAction.close();
      },
      async toggle() {
        // Firefox 没有原生 toggle，需要手动判断
        await (chrome as any).sidebarAction.open();
      },
    };
  }

  // Chrome/Edge 使用 sidePanel
  return {
    async open() {
      await (chrome as any).sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
    },
    async close() {
      // Chrome sidePanel 没有直接 close API
    },
    async toggle() {
      await (chrome as any).sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
    },
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
