/**
 * 求问 — Chrome Storage 状态存储
 * ===============================
 *
 * 职责：
 *   - 封装 chrome.storage.local 读写
 *   - 球体状态持久化
 *   - 聊天历史持久化
 *   - 设置读写
 *
 * 从 service_worker.ts 拆分而来。
 */

import { STORAGE_KEYS } from "../common/constants";
import type { BallState, ChatMessage } from "../common/types";

export class StateStore {
  // -----------------------------------------------------------------------
  // 球体状态
  // -----------------------------------------------------------------------

  /** 保存球体状态。 */
  async setBallState(state: BallState): Promise<void> {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [STORAGE_KEYS.BALL_STATE]: state }, resolve);
    });
  }

  /** 读取球体状态。 */
  async getBallState(): Promise<BallState> {
    return new Promise((resolve) => {
      chrome.storage.local.get([STORAGE_KEYS.BALL_STATE], (data) => {
        resolve(data[STORAGE_KEYS.BALL_STATE] || "idle");
      });
    });
  }

  // -----------------------------------------------------------------------
  // 聊天历史
  // -----------------------------------------------------------------------

  /** 追加聊天消息。 */
  async appendChatMessage(msg: ChatMessage): Promise<void> {
    const history = await this.getChatHistory();
    history.push(msg);
    // 保留最近 100 条
    const trimmed = history.slice(-100);
    return new Promise((resolve) => {
      chrome.storage.local.set({ [STORAGE_KEYS.CHAT_HISTORY]: trimmed }, resolve);
    });
  }

  /** 获取聊天历史。 */
  async getChatHistory(): Promise<ChatMessage[]> {
    return new Promise((resolve) => {
      chrome.storage.local.get([STORAGE_KEYS.CHAT_HISTORY], (data) => {
        resolve(data[STORAGE_KEYS.CHAT_HISTORY] || []);
      });
    });
  }

  /** 清空聊天历史。 */
  async clearChatHistory(): Promise<void> {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [STORAGE_KEYS.CHAT_HISTORY]: [] }, resolve);
    });
  }

  // -----------------------------------------------------------------------
  // 会话 ID
  // -----------------------------------------------------------------------

  async setSessionId(id: string): Promise<void> {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [STORAGE_KEYS.SESSION_ID]: id }, resolve);
    });
  }

  async getSessionId(): Promise<string | null> {
    return new Promise((resolve) => {
      chrome.storage.local.get([STORAGE_KEYS.SESSION_ID], (data) => {
        resolve(data[STORAGE_KEYS.SESSION_ID] || null);
      });
    });
  }

  // -----------------------------------------------------------------------
  // 设置
  // -----------------------------------------------------------------------

  async getSettings(): Promise<Record<string, any>> {
    return new Promise((resolve) => {
      chrome.storage.local.get([STORAGE_KEYS.SETTINGS], (data) => {
        resolve(data[STORAGE_KEYS.SETTINGS] || {});
      });
    });
  }

  async setSettings(settings: Record<string, any>): Promise<void> {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [STORAGE_KEYS.SETTINGS]: settings }, resolve);
    });
  }

  // -----------------------------------------------------------------------
  // 初始化
  // -----------------------------------------------------------------------

  /** 首次安装时初始化默认值。 */
  async initializeDefaults(): Promise<void> {
    return new Promise((resolve) => {
      chrome.storage.local.set({
        [STORAGE_KEYS.SETTINGS]: { wsUrl: "ws://localhost:8700/ws/chat" },
        [STORAGE_KEYS.CHAT_HISTORY]: [],
        [STORAGE_KEYS.BALL_STATE]: "idle",
      }, resolve);
    });
  }
}
