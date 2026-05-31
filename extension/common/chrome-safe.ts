/**
 * 求问 — Chrome API 安全封装
 * ============================
 *
 * 解决 "Extension context invalidated" 错误。
 *
 * 核心策略：所有 Chrome API 调用使用 async/await + try-catch，
 * 确保 Promise rejection 一定被捕获，不触发 unhandledrejection。
 */

// ---------------------------------------------------------------------------
// 上下文检测
// ---------------------------------------------------------------------------

/** 检测扩展上下文是否有效。 */
export function isContextAlive(): boolean {
  try {
    return !!chrome?.runtime?.id;
  } catch {
    return false;
  }
}

let _alive = true;

export function isAlive(): boolean {
  return _alive;
}

export function markDead(): void {
  if (!_alive) return; // 只输出一次
  _alive = false;
  clearAllTimers();
  console.warn("[求问] 扩展上下文已失效，请刷新页面");
}

/** 判断错误是否为扩展上下文失效。 */
function isContextError(msg: string): boolean {
  return msg.includes("Extension context invalidated")
    || msg.includes("receiving end does not exist")
    || msg.includes("message port closed");
}

// ---------------------------------------------------------------------------
// 安全的 chrome.runtime.sendMessage（async/await 模式）
// ---------------------------------------------------------------------------

/**
 * 安全发送消息到 Service Worker。
 *
 * 关键：使用同步 .catch() 而非 async/await。
 * 浏览器在 Promise 创建时就能看到 catch handler，
 * 不会将 rejection 标记为"未处理"，从而避免 unhandledrejection。
 */
export function safeSend(msg: any): void {
  if (!_alive) return;
  if (!isContextAlive()) {
    markDead();
    return;
  }
  try {
    // 同步附加 .catch()，浏览器立即看到 handler
    chrome.runtime.sendMessage(msg).catch((e: any) => {
      if (isContextError(e?.message || String(e))) {
        markDead();
      }
    });
  } catch (e: any) {
    // chrome.runtime 未定义时的同步异常
    if (isContextError(e?.message || String(e))) {
      markDead();
    }
  }
}

// ---------------------------------------------------------------------------
// 安全的 chrome.storage
// ---------------------------------------------------------------------------

/**
 * 安全读取 chrome.storage.local。
 * 上下文失效时返回默认值。
 */
export async function safeStorageGet(keys: string[]): Promise<Record<string, any>> {
  if (!_alive) return {};
  if (!isContextAlive()) { markDead(); return {}; }
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(keys, (data) => {
        if (chrome.runtime.lastError) {
          if (isContextError(chrome.runtime.lastError.message || "")) markDead();
          resolve({});
          return;
        }
        resolve(data || {});
      });
    } catch (e: any) {
      if (isContextError(e?.message || String(e))) markDead();
      resolve({});
    }
  });
}

/**
 * 安全写入 chrome.storage.local。
 * 上下文失效时静默失败。
 */
export async function safeStorageSet(items: Record<string, any>): Promise<void> {
  if (!_alive) return;
  if (!isContextAlive()) { markDead(); return; }
  return new Promise((resolve) => {
    try {
      chrome.storage.local.set(items, () => {
        if (chrome.runtime.lastError) {
          if (isContextError(chrome.runtime.lastError.message || "")) markDead();
        }
        resolve();
      });
    } catch (e: any) {
      if (isContextError(e?.message || String(e))) markDead();
      resolve();
    }
  });
}

// ---------------------------------------------------------------------------
// 安全的 chrome.tabs.sendMessage
// ---------------------------------------------------------------------------

/**
 * 安全发送消息到指定 Tab 的 Content Script。
 */
export async function safeTabSend(tabId: number, msg: any): Promise<void> {
  if (!_alive) return;
  try {
    await chrome.tabs.sendMessage(tabId, msg);
  } catch {
    // Content Script 可能未注入，静默忽略
  }
}

// ---------------------------------------------------------------------------
// 定时器管理（失效时自动清理）
// ---------------------------------------------------------------------------

const _timers = new Set<ReturnType<typeof setTimeout>>();
const _intervals = new Set<ReturnType<typeof setInterval>>();

/**
 * 安全的 setTimeout，扩展失效时自动取消。
 */
export function safeSetTimeout(fn: () => void, ms: number): ReturnType<typeof setTimeout> {
  const id = setTimeout(() => {
    _timers.delete(id);
    if (_alive) fn();
  }, ms);
  _timers.add(id);
  return id;
}

/**
 * 安全的 setInterval，扩展失效时自动取消。
 */
export function safeSetInterval(fn: () => void, ms: number): ReturnType<typeof setInterval> {
  const id = setInterval(() => {
    if (!_alive) {
      clearInterval(id);
      _intervals.delete(id);
      return;
    }
    fn();
  }, ms);
  _intervals.add(id);
  return id;
}

/**
 * 清理所有定时器。
 */
export function clearAllTimers(): void {
  for (const id of _timers) clearTimeout(id);
  for (const id of _intervals) clearInterval(id);
  _timers.clear();
  _intervals.clear();
}

/**
 * 完全清理（扩展失效时调用）。
 */
export function cleanup(): void {
  markDead();
}
