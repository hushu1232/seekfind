/**
 * 求问 — 文档导入向导
 * =====================
 *
 * 职责：
 *   - 三种导入方式：输入 URL / 拖拽本地文件 / 粘贴文本
 *   - 触发后端索引构建
 *   - 进度条显示
 */

import { API_BASE } from "../common/constants";

/**
 * 渲染文档导入向导。
 */
export function renderImportWizard(container: HTMLElement): void {
  container.innerHTML = `
    <div style="padding: 16px; font-size: 14px;">
      <h3 style="margin-bottom: 16px; font-size: 15px;">📥 导入文档</h3>
      <p style="font-size: 12px; color: #6c757d; margin-bottom: 16px;">
        导入产品文档后，我能更准确地回答你的问题。
      </p>

      <!-- 方式一：URL -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 6px;">🔗 输入文档 URL</label>
        <div style="display: flex; gap: 6px;">
          <input type="text" id="import-url" placeholder="https://docs.example.com"
            style="flex: 1; padding: 8px 12px; border: 1px solid #e9ecef; border-radius: 6px; font-size: 13px;" />
          <button id="import-url-btn" style="padding: 8px 14px; background: #4A90D9; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">爬取</button>
        </div>
      </div>

      <!-- 方式二：拖拽文件 -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 6px;">📁 拖拽本地文件</label>
        <div id="drop-zone" style="
          border: 2px dashed #e9ecef;
          border-radius: 8px;
          padding: 24px;
          text-align: center;
          color: #6c757d;
          cursor: pointer;
          transition: all 0.15s;
        ">
          拖拽 .md / .html / .txt 文件到这里
          <br><span style="font-size: 12px;">或点击选择文件</span>
          <input type="file" id="file-input" accept=".md,.html,.txt,.json" style="display: none;" multiple />
        </div>
      </div>

      <!-- 方式三：粘贴文本 -->
      <div style="margin-bottom: 20px;">
        <label style="display: block; font-weight: 600; margin-bottom: 6px;">📋 粘贴文档文本</label>
        <textarea id="import-text" placeholder="粘贴文档内容..." rows="4"
          style="width: 100%; padding: 8px 12px; border: 1px solid #e9ecef; border-radius: 6px; font-size: 13px; resize: vertical;"></textarea>
        <button id="import-text-btn" style="margin-top: 6px; padding: 8px 14px; background: #4A90D9; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">导入</button>
      </div>

      <!-- 进度条 -->
      <div id="import-progress" style="display: none;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
          <span id="progress-text" style="font-size: 13px;">正在导入...</span>
          <span id="progress-percent" style="font-size: 13px; color: #4A90D9; font-weight: 600;">0%</span>
        </div>
        <div style="background: #e9ecef; border-radius: 4px; height: 8px; overflow: hidden;">
          <div id="progress-bar" style="background: #4A90D9; height: 100%; width: 0%; transition: width 0.3s;"></div>
        </div>
      </div>

      <!-- 状态消息 -->
      <div id="import-status" style="margin-top: 12px; font-size: 13px;"></div>
    </div>
  `;

  // --- 事件绑定 ---

  // URL 导入
  const urlInput = container.querySelector("#import-url") as HTMLInputElement;
  const urlBtn = container.querySelector("#import-url-btn") as HTMLButtonElement;
  urlBtn?.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (url) importFromUrl(url, container);
  });

  // 拖拽文件
  const dropZone = container.querySelector("#drop-zone") as HTMLDivElement;
  const fileInput = container.querySelector("#file-input") as HTMLInputElement;

  dropZone?.addEventListener("click", () => fileInput.click());
  dropZone?.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "#4A90D9";
    dropZone.style.background = "#e8f0fe";
  });
  dropZone?.addEventListener("dragleave", () => {
    dropZone.style.borderColor = "#e9ecef";
    dropZone.style.background = "transparent";
  });
  dropZone?.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "#e9ecef";
    dropZone.style.background = "transparent";
    const files = e.dataTransfer?.files;
    if (files) importFromFiles(files, container);
  });
  fileInput?.addEventListener("change", () => {
    if (fileInput.files) importFromFiles(fileInput.files, container);
  });

  // 文本导入
  const textArea = container.querySelector("#import-text") as HTMLTextAreaElement;
  const textBtn = container.querySelector("#import-text-btn") as HTMLButtonElement;
  textBtn?.addEventListener("click", () => {
    const text = textArea.value.trim();
    if (text) importFromText(text, container);
  });
}

/**
 * 从 URL 导入（触发后端爬取 + 索引）。
 */
async function importFromUrl(url: string, container: HTMLElement): Promise<void> {
  showProgress(container, "正在爬取文档...", 10);

  try {
    const resp = await fetch("${API_BASE}/api/index/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    showProgress(container, "索引构建完成！", 100);
    showStatus(container, `✅ 成功导入 ${data.chunks || 0} 个文档块`, "success");
  } catch (e: any) {
    showStatus(container, `❌ 导入失败: ${e.message}`, "error");
  }
}

/**
 * 从本地文件导入。
 */
async function importFromFiles(files: FileList, container: HTMLElement): Promise<void> {
  showProgress(container, "正在读取文件...", 20);

  for (const file of Array.from(files)) {
    const text = await file.text();
    showProgress(container, `正在导入 ${file.name}...`, 50);

    try {
      const resp = await fetch("${API_BASE}/api/index/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, title: file.name }),
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch (e: any) {
      showStatus(container, `❌ ${file.name} 导入失败: ${e.message}`, "error");
      return;
    }
  }

  showProgress(container, "导入完成！", 100);
  showStatus(container, `✅ 成功导入 ${files.length} 个文件`, "success");
}

/**
 * 从粘贴文本导入。
 */
async function importFromText(text: string, container: HTMLElement): Promise<void> {
  showProgress(container, "正在导入...", 50);

  try {
    const resp = await fetch("${API_BASE}/api/index/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, title: "用户粘贴文本" }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    showProgress(container, "导入完成！", 100);
    showStatus(container, `✅ 成功导入 ${data.chunks || 0} 个文档块`, "success");
  } catch (e: any) {
    showStatus(container, `❌ 导入失败: ${e.message}`, "error");
  }
}

function showProgress(container: HTMLElement, text: string, percent: number): void {
  const progressEl = container.querySelector("#import-progress") as HTMLDivElement;
  const textEl = container.querySelector("#progress-text") as HTMLSpanElement;
  const percentEl = container.querySelector("#progress-percent") as HTMLSpanElement;
  const barEl = container.querySelector("#progress-bar") as HTMLDivElement;

  progressEl.style.display = "block";
  textEl.textContent = text;
  percentEl.textContent = `${percent}%`;
  barEl.style.width = `${percent}%`;
}

function showStatus(container: HTMLElement, message: string, type: "success" | "error"): void {
  const statusEl = container.querySelector("#import-status") as HTMLDivElement;
  statusEl.textContent = message;
  statusEl.style.color = type === "success" ? "#28a745" : "#dc3545";
}
