/**
 * 求问 — 状态自检与诊断
 * ======================
 *
 * 职责：
 *   1. 检测后端连接状态
 *   2. 检测 Ollama 服务状态
 *   3. 检测 AI 模型加载状态
 *   4. 检测 Chroma 向量库状态
 *   5. 检测 WebSocket 连接状态
 *   6. 提供一键修复建议
 */

import { API_BASE } from "../common/constants";

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------
export interface CheckResult {
  name: string;
  label: string;
  ok: boolean;
  message: string;
  fix?: FixAction;
}

export interface FixAction {
  label: string;
  description: string;
  autoFix: boolean;
  action?: string;
}

export interface DiagnosticReport {
  overall: "healthy" | "degraded" | "error";
  checks: CheckResult[];
  fixes: FixAction[];
}

// ---------------------------------------------------------------------------
// 诊断类
// ---------------------------------------------------------------------------
class Diagnostics {
  /**
   * 运行完整诊断
   */
  async runFullCheck(): Promise<DiagnosticReport> {
    const checks = await Promise.all([
      this.checkBackendConnection(),
      this.checkOllamaStatus(),
      this.checkModelLoaded(),
      this.checkChromaStatus(),
      this.checkMemoryUsage(),
    ]);

    const failed = checks.filter((c) => !c.ok);
    const overall =
      failed.length === 0
        ? "healthy"
        : failed.some((f) => f.name === "backend")
          ? "error"
          : "degraded";

    return {
      overall,
      checks,
      fixes: failed.map((c) => c.fix).filter(Boolean) as FixAction[],
    };
  }

  /**
   * 检测后端连接
   */
  private async checkBackendConnection(): Promise<CheckResult> {
    try {
      const resp = await fetch(`${API_BASE}/health`, {
        signal: AbortSignal.timeout(3000),
      });
      const data = await resp.json();

      if (data.status === "ok") {
        return {
          name: "backend",
          label: "后端连接",
          ok: true,
          message: "正常",
        };
      }

      return {
        name: "backend",
        label: "后端连接",
        ok: false,
        message: "响应异常",
        fix: {
          label: "重启后端",
          description: "执行 docker compose restart",
          autoFix: false,
          action: "docker compose restart",
        },
      };
    } catch (e) {
      return {
        name: "backend",
        label: "后端连接",
        ok: false,
        message: "无法连接",
        fix: {
          label: "启动后端",
          description: "执行 docker compose up -d",
          autoFix: false,
          action: "docker compose up -d",
        },
      };
    }
  }

  /**
   * 检测 Ollama 服务
   */
  private async checkOllamaStatus(): Promise<CheckResult> {
    try {
      const resp = await fetch("http://localhost:11434/api/tags", {
        signal: AbortSignal.timeout(2000),
      });
      const data = await resp.json();
      const modelCount = data.models?.length || 0;

      return {
        name: "ollama",
        label: "Ollama 服务",
        ok: true,
        message: `运行中 (${modelCount} 个模型)`,
      };
    } catch (e) {
      return {
        name: "ollama",
        label: "Ollama 服务",
        ok: false,
        message: "未运行",
        fix: {
          label: "启动 Ollama",
          description: "在终端执行 ollama serve",
          autoFix: false,
          action: "ollama serve",
        },
      };
    }
  }

  /**
   * 检测 AI 模型
   */
  private async checkModelLoaded(): Promise<CheckResult> {
    try {
      const resp = await fetch("http://localhost:11434/api/tags", {
        signal: AbortSignal.timeout(2000),
      });
      const data = await resp.json();

      const hasModel = data.models?.some(
        (m: any) =>
          m.name.includes("qwen2.5:7b") ||
          m.name.includes("qwen2.5:3b") ||
          m.name.includes("qwen2.5:14b")
      );

      if (hasModel) {
        return {
          name: "model",
          label: "AI 模型",
          ok: true,
          message: "已就绪",
        };
      }

      return {
        name: "model",
        label: "AI 模型",
        ok: false,
        message: "未找到模型",
        fix: {
          label: "下载模型",
          description: "执行 ollama pull qwen2.5:7b (约 4GB)",
          autoFix: true,
          action: "ollama pull qwen2.5:7b",
        },
      };
    } catch (e) {
      return {
        name: "model",
        label: "AI 模型",
        ok: false,
        message: "无法检测",
      };
    }
  }

  /**
   * 检测 Chroma 向量库
   */
  private async checkChromaStatus(): Promise<CheckResult> {
    try {
      const resp = await fetch(`${API_BASE}/api/status`, {
        signal: AbortSignal.timeout(3000),
      });
      const data = await resp.json();

      if (data.chroma) {
        return {
          name: "chroma",
          label: "向量库",
          ok: true,
          message: "正常",
        };
      }

      return {
        name: "chroma",
        label: "向量库",
        ok: false,
        message: "未连接",
        fix: {
          label: "重启服务",
          description: "执行 docker compose restart",
          autoFix: false,
          action: "docker compose restart",
        },
      };
    } catch (e) {
      return {
        name: "chroma",
        label: "向量库",
        ok: false,
        message: "无法检测",
      };
    }
  }

  /**
   * 检测内存使用
   */
  private async checkMemoryUsage(): Promise<CheckResult> {
    try {
      const resp = await fetch(`${API_BASE}/api/status`, {
        signal: AbortSignal.timeout(3000),
      });
      const data = await resp.json();

      if (data.memory) {
        const used = data.memory.used || 0;
        const total = data.memory.total || 1;
        const percent = Math.round((used / total) * 100);

        if (percent > 90) {
          return {
            name: "memory",
            label: "内存使用",
            ok: false,
            message: `${percent}% (过高)`,
            fix: {
              label: "清理内存",
              description: "重启后端服务释放内存",
              autoFix: false,
              action: "docker compose restart",
            },
          };
        }

        return {
          name: "memory",
          label: "内存使用",
          ok: true,
          message: `${percent}%`,
        };
      }

      return {
        name: "memory",
        label: "内存使用",
        ok: true,
        message: "正常",
      };
    } catch (e) {
      return {
        name: "memory",
        label: "内存使用",
        ok: true,
        message: "无法检测",
      };
    }
  }

  /**
   * 执行一键修复
   */
  async executeFix(fix: FixAction): Promise<boolean> {
    if (!fix.action) return false;

    try {
      // 对于需要用户手动执行的命令，复制到剪贴板
      if (!fix.autoFix) {
        await navigator.clipboard.writeText(fix.action);
        return true;
      }

      // 对于可自动修复的，通过后端 API 执行
      const resp = await fetch(`${API_BASE}/api/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: fix.action }),
      });

      return resp.ok;
    } catch (e) {
      return false;
    }
  }
}

// ---------------------------------------------------------------------------
// 全局单例
// ---------------------------------------------------------------------------
let diagnostics: Diagnostics | null = null;

export function getDiagnostics(): Diagnostics {
  if (!diagnostics) {
    diagnostics = new Diagnostics();
  }
  return diagnostics;
}

// ---------------------------------------------------------------------------
// 渲染诊断结果
// ---------------------------------------------------------------------------
export function renderDiagnosticReport(
  container: HTMLElement,
  report: DiagnosticReport
): void {
  container.innerHTML = "";

  // 总体状态
  const header = document.createElement("div");
  header.className = "diagnostic-header";

  const statusIcon = document.createElement("span");
  statusIcon.className = `diagnostic-status ${report.overall}`;
  statusIcon.textContent =
    report.overall === "healthy"
      ? "✅"
      : report.overall === "degraded"
        ? "⚠️"
        : "❌";

  const statusText = document.createElement("span");
  statusText.className = "diagnostic-status-text";
  statusText.textContent =
    report.overall === "healthy"
      ? "系统正常"
      : report.overall === "degraded"
        ? "部分功能受限"
        : "系统异常";

  header.appendChild(statusIcon);
  header.appendChild(statusText);
  container.appendChild(header);

  // 检查项列表
  const list = document.createElement("div");
  list.className = "diagnostic-list";

  for (const check of report.checks) {
    const item = document.createElement("div");
    item.className = `diagnostic-item ${check.ok ? "ok" : "error"}`;

    const icon = document.createElement("span");
    icon.className = "diagnostic-item-icon";
    icon.textContent = check.ok ? "✅" : "❌";

    const label = document.createElement("span");
    label.className = "diagnostic-item-label";
    label.textContent = check.label;

    const message = document.createElement("span");
    message.className = "diagnostic-item-message";
    message.textContent = check.message;

    item.appendChild(icon);
    item.appendChild(label);
    item.appendChild(message);

    if (check.fix && !check.ok) {
      const fixBtn = document.createElement("button");
      fixBtn.className = "diagnostic-fix-btn";
      fixBtn.textContent = check.fix.label;
      fixBtn.title = check.fix.description;

      fixBtn.addEventListener("click", async () => {
        fixBtn.disabled = true;
        fixBtn.textContent = "执行中...";

        const success = await getDiagnostics().executeFix(check.fix!);
        if (success) {
          fixBtn.textContent = check.fix!.autoFix ? "已修复" : "已复制命令";
        } else {
          fixBtn.textContent = "失败";
        }
      });

      item.appendChild(fixBtn);
    }

    list.appendChild(item);
  }

  container.appendChild(list);

  // 修复建议
  if (report.fixes.length > 0) {
    const fixesSection = document.createElement("div");
    fixesSection.className = "diagnostic-fixes";

    const fixesTitle = document.createElement("div");
    fixesTitle.className = "diagnostic-fixes-title";
    fixesTitle.textContent = "修复建议";
    fixesSection.appendChild(fixesTitle);

    for (const fix of report.fixes) {
      const fixItem = document.createElement("div");
      fixItem.className = "diagnostic-fix-item";
      fixItem.innerHTML = `
        <span class="fix-label">${fix.label}</span>
        <span class="fix-desc">${fix.description}</span>
      `;
      fixesSection.appendChild(fixItem);
    }

    container.appendChild(fixesSection);
  }
}
