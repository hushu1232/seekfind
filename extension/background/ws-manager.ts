/**
 * 求问 — WebSocket 连接管理器
 * ============================
 *
 * 职责：
 *   - WebSocket 连接 / 断线重连 / 心跳
 *   - 连接状态事件通知
 *   - 速率限制（防刷）
 *
 * 从 service_worker.ts 拆分而来，降低单文件复杂度。
 */

import { WS_URL, WS_RECONNECT_INTERVAL, WS_HEARTBEAT_INTERVAL } from "../common/constants";
import type { ClientMessage, ServerMessage } from "../common/types";

/** 连接状态回调 */
type StatusCallback = (connected: boolean) => void;
/** 消息回调 */
type MessageCallback = (msg: ServerMessage) => void;

/** 速率限制配置 */
const RATE_LIMIT_MAX = 10; // 每秒最多发送 10 条消息
const RATE_LIMIT_WINDOW = 1000; // 1 秒窗口

export class WSManager {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private onStatus: StatusCallback | null = null;
  private onMessage: MessageCallback | null = null;

  // 速率限制
  private sendTimestamps: number[] = [];

  /**
   * 注册回调。
   */
  setCallbacks(onStatus: StatusCallback, onMessage: MessageCallback): void {
    this.onStatus = onStatus;
    this.onMessage = onMessage;
  }

  /** 建立连接。 */
  connect(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(WS_URL);

    this.ws.onopen = () => {
      console.log("[WSManager] 已连接");
      this.onStatus?.(true);
      this.startHeartbeat();
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        this.onMessage?.(msg);
      } catch (e) {
        console.error("[WSManager] 消息解析失败:", e);
      }
    };

    this.ws.onclose = () => {
      console.log("[WSManager] 已断开");
      this.onStatus?.(false);
      this.stopHeartbeat();
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error("[WSManager] 错误:", err);
    };
  }

  /** 发送消息（带速率限制）。 */
  send(msg: ClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    // 速率限制检查
    if (!this.checkRateLimit()) {
      console.warn("[WSManager] 速率限制，消息被丢弃");
      return;
    }

    this.ws.send(JSON.stringify(msg));
  }

  /** 速率限制检查。返回 true 表示允许发送。 */
  private checkRateLimit(): boolean {
    const now = Date.now();
    // 清理窗口外的旧时间戳
    this.sendTimestamps = this.sendTimestamps.filter((t) => now - t < RATE_LIMIT_WINDOW);

    if (this.sendTimestamps.length >= RATE_LIMIT_MAX) {
      return false;
    }

    this.sendTimestamps.push(now);
    return true;
  }

  /** 是否已连接。 */
  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, WS_RECONNECT_INTERVAL);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: "ping" });
    }, WS_HEARTBEAT_INTERVAL);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}
