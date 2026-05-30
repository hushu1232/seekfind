/**
 * 求问 — 设置面板
 * =================
 *
 * 职责：
 *   - 模型选择 UI（本地 / 云端 / 混合）
 *   - 语音设置（麦克风开关、语音选择）
 *   - 隐私设置（脱敏开关、历史学习开关）
 *   - 调用后端 /api/config/model 热切换模型
 *
 * 布局：
 *   ┌─────────────────────────┐
 *   │  ⚙️ 设置                │
 *   │                         │
 *   │  AI 模型                │
 *   │  [本地] [混合] [云端]   │
 *   │  当前: qwen2.5:7b      │
 *   │                         │
 *   │  语音                   │
 *   │  [🎤 麦克风] [开关]     │
 *   │                         │
 *   │  隐私                   │
 *   │  [自动脱敏] [开关]      │
 *   │  [历史学习] [开关]      │
 *   │                         │
 *   │  [清除数据] [重置]      │
 *   └─────────────────────────┘
 */

import { STORAGE_KEYS, DEFAULT_SETTINGS, DEFAULT_PRIVACY, API_BASE } from "../common/constants";

type ModelStrategy = "local" | "cloud" | "hybrid";

interface Settings {
  wsUrl: string;
  modelStrategy: ModelStrategy;
  autoListen: boolean;
  showNotifications: boolean;
}

interface Privacy {
  sanitizeEnabled: boolean;
  historyLearningEnabled: boolean;
  collectInputs: boolean;
}

/** 加载设置 */
export async function loadSettings(): Promise<Settings> {
  return new Promise((resolve) => {
    chrome.storage.local.get([STORAGE_KEYS.SETTINGS], (data) => {
      resolve({ ...DEFAULT_SETTINGS, ...data[STORAGE_KEYS.SETTINGS] });
    });
  });
}

/** 保存设置 */
export async function saveSettings(settings: Settings): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEYS.SETTINGS]: settings }, resolve);
  });
}

/** 加载隐私设置 */
export async function loadPrivacy(): Promise<Privacy> {
  return new Promise((resolve) => {
    chrome.storage.local.get([STORAGE_KEYS.PRIVACY], (data) => {
      resolve({ ...DEFAULT_PRIVACY, ...data[STORAGE_KEYS.PRIVACY] });
    });
  });
}

/** 保存隐私设置 */
export async function savePrivacy(privacy: Privacy): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEYS.PRIVACY]: privacy }, resolve);
  });
}

/**
 * 渲染设置面板。
 */
export async function renderSettingsPanel(container: HTMLElement): Promise<void> {
  const settings = await loadSettings();
  const privacy = await loadPrivacy();

  container.innerHTML = `
    <div style="padding: 16px; font-size: 14px;">
      <h3 style="margin-bottom: 16px; font-size: 15px;">⚙️ 设置</h3>

      <!-- AI 模型 -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 8px;">AI 模型策略</label>
        <div style="display: flex; gap: 6px; margin-bottom: 8px;">
          <button class="model-btn ${settings.modelStrategy === 'local' ? 'active' : ''}" data-strategy="local">🏠 本地</button>
          <button class="model-btn ${settings.modelStrategy === 'hybrid' ? 'active' : ''}" data-strategy="hybrid">🔄 混合</button>
          <button class="model-btn ${settings.modelStrategy === 'cloud' ? 'active' : ''}" data-strategy="cloud">☁️ 云端</button>
        </div>
        <div style="font-size: 12px; color: #6c757d;">
          当前模型: <strong>${settings.modelStrategy === 'cloud' ? '云端 API' : '本地 Ollama'}</strong>
        </div>
      </div>

      <!-- 语音 -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 8px;">语音交互</label>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
          <span>🎤 自动监听唤醒词</span>
          <input type="checkbox" id="auto-listen" ${settings.autoListen ? 'checked' : ''} />
        </div>
      </div>

      <!-- 隐私 -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 8px;">隐私保护</label>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
          <span>🔒 自动脱敏</span>
          <input type="checkbox" id="privacy-sanitize" ${privacy.sanitizeEnabled ? 'checked' : ''} />
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
          <span>📚 浏览历史学习</span>
          <input type="checkbox" id="privacy-history" ${privacy.historyLearningEnabled ? 'checked' : ''} />
        </div>
      </div>

      <!-- 操作按钮 -->
      <div style="display: flex; gap: 8px;">
        <button id="clear-data" style="flex:1; padding: 8px; border: 1px solid #dc3545; color: #dc3545; border-radius: 6px; background: white; cursor: pointer;">🗑️ 清除数据</button>
        <button id="reset-settings" style="flex:1; padding: 8px; border: 1px solid #6c757d; color: #6c757d; border-radius: 6px; background: white; cursor: pointer;">↩️ 重置</button>
      </div>
    </div>

    <style>
      .model-btn {
        flex: 1;
        padding: 8px 4px;
        border: 1px solid #e9ecef;
        border-radius: 6px;
        background: white;
        cursor: pointer;
        font-size: 13px;
        transition: all 0.15s;
      }
      .model-btn:hover { background: #f8f9fa; }
      .model-btn.active {
        border-color: #4A90D9;
        background: #e8f0fe;
        color: #4A90D9;
        font-weight: 600;
      }
      input[type="checkbox"] {
        width: 18px; height: 18px;
        cursor: pointer;
      }
    </style>
  `;

  // --- 事件绑定 ---

  // 模型策略切换
  container.querySelectorAll(".model-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const strategy = (btn as HTMLElement).dataset.strategy as ModelStrategy;
      settings.modelStrategy = strategy;
      await saveSettings(settings);

      // 通知后端热切换
      fetch(`${API_BASE}/api/config/model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_strategy: strategy }),
      }).catch(() => {});

      // 更新 UI
      container.querySelectorAll(".model-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // 自动监听
  container.querySelector("#auto-listen")?.addEventListener("change", async (e) => {
    settings.autoListen = (e.target as HTMLInputElement).checked;
    await saveSettings(settings);
  });

  // 隐私脱敏
  container.querySelector("#privacy-sanitize")?.addEventListener("change", async (e) => {
    privacy.sanitizeEnabled = (e.target as HTMLInputElement).checked;
    await savePrivacy(privacy);
  });

  // 历史学习
  container.querySelector("#privacy-history")?.addEventListener("change", async (e) => {
    privacy.historyLearningEnabled = (e.target as HTMLInputElement).checked;
    await savePrivacy(privacy);
  });

  // 清除数据
  container.querySelector("#clear-data")?.addEventListener("click", () => {
    if (confirm("确定清除所有数据？（聊天历史、设置、记忆）")) {
      chrome.storage.local.clear();
      window.location.reload();
    }
  });

  // 重置
  container.querySelector("#reset-settings")?.addEventListener("click", async () => {
    await saveSettings(DEFAULT_SETTINGS as any);
    await savePrivacy(DEFAULT_PRIVACY as any);
    window.location.reload();
  });
}
