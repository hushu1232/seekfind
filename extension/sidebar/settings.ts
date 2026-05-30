/**
 * 求问 — 设置面板
 * Phase 4 实现阶段，当前为骨架代码。
 */

import { STORAGE_KEYS, DEFAULT_SETTINGS } from "../common/constants";

/** 模型策略 */
type ModelStrategy = "local" | "cloud" | "hybrid";

/** 设置数据 */
interface Settings {
  wsUrl: string;
  modelStrategy: ModelStrategy;
  autoListen: boolean;
  showNotifications: boolean;
}

/**
 * 加载设置。
 */
export async function loadSettings(): Promise<Settings> {
  return new Promise((resolve) => {
    chrome.storage.local.get([STORAGE_KEYS.SETTINGS], (data) => {
      resolve({ ...DEFAULT_SETTINGS, ...data[STORAGE_KEYS.SETTINGS] });
    });
  });
}

/**
 * 保存设置。
 */
export async function saveSettings(settings: Settings): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEYS.SETTINGS]: settings }, resolve);
  });
}

/**
 * 渲染设置面板。
 * TODO: Phase 4 实现完整的设置 UI。
 */
export function renderSettingsPanel(container: HTMLElement): void {
  container.innerHTML = `
    <div style="padding: 16px;">
      <h3 style="margin-bottom: 12px;">⚙️ 设置</h3>
      <div style="margin-bottom: 12px;">
        <label style="display: block; font-size: 13px; color: #6c757d; margin-bottom: 4px;">
          AI 模型策略
        </label>
        <select id="model-strategy" style="width: 100%; padding: 8px; border: 1px solid #e9ecef; border-radius: 6px;">
          <option value="local">本地模型（零成本）</option>
          <option value="cloud">云端模型（需 API Key）</option>
          <option value="hybrid">混合模式（推荐）</option>
        </select>
      </div>
    </div>
  `;
}
