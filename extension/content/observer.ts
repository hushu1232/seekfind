/**
 * 求问 — Content Script: DOM 观察者
 * ====================================
 *
 * 职责：
 *   1. 页面就绪上报（URL / 标题）
 *   2. 事件采集（click / input / scroll / route_change / dom_change）
 *   3. 操作流录制模式（记录用户操作序列）
 *   4. 主动监控（检测用户困惑 → 主动提示）
 *
 * 注入时机：document_start
 * 隐私：事件采集默认关闭，需用户在设置中开启。
 */

import { INTERNAL_MSG } from "../common/constants";
import type { PageEvent } from "../common/types";
import { injectAtStart } from "../common/browser-compat";
import { sanitizeText, isPasswordField } from "./privacy";
import { takeSnapshot, findElement, executeInteraction } from "./snapshot";

injectAtStart(() => {
  // -----------------------------------------------------------------------
  // 状态
  // -----------------------------------------------------------------------
  let monitoringEnabled = false;
  let recordingMode = false;
  let recordedSteps: Array<{
    action: string;
    selector: string;
    description: string;
    value?: string;
    timestamp: number;
  }> = [];

  // 用户困惑检测状态
  let clickCount = 0;
  let lastClickTarget = "";
  let lastClickTime = 0;
  const CONFUSION_THRESHOLD = 3; // 连续点击同一元素 N 次视为困惑
  const CONFUSION_WINDOW = 5000; // 5 秒窗口

  // -----------------------------------------------------------------------
  // 页面就绪上报
  // -----------------------------------------------------------------------
  function notifyPageReady(): void {
    chrome.runtime.sendMessage({
      type: INTERNAL_MSG.PAGE_READY,
      url: window.location.href,
      title: document.title,
    });
  }

  if (document.readyState === "complete") {
    notifyPageReady();
  } else {
    window.addEventListener("load", notifyPageReady);
  }

  // -----------------------------------------------------------------------
  // 消息监听（控制采集/录制模式）
  // -----------------------------------------------------------------------
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "qiuwen:enable_monitoring") {
      monitoringEnabled = true;
      console.log("[求问] 事件采集已开启");
    }
    if (msg.type === "qiuwen:disable_monitoring") {
      monitoringEnabled = false;
      console.log("[求问] 事件采集已关闭");
    }
    if (msg.type === "qiuwen:start_recording") {
      recordingMode = true;
      recordedSteps = [];
      console.log("[求问] 操作流录制已开始");
    }
    if (msg.type === "qiuwen:stop_recording") {
      recordingMode = false;
      // 发送录制结果到 Service Worker
      chrome.runtime.sendMessage({
        type: "qiuwen:recorded_steps",
        steps: recordedSteps,
      });
      console.log("[求问] 操作流录制已停止", { steps: recordedSteps.length });
    }

    // 浏览器控制：无障碍树快照
    if (msg.type === INTERNAL_MSG.SNAPSHOT) {
      const result = takeSnapshot(msg.options || {});
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.SNAPSHOT_RESULT,
        ...result,
      });
    }

    // 浏览器控制：语义查找
    if (msg.type === INTERNAL_MSG.FIND_ELEMENT) {
      const ref = findElement(msg.strategy, msg.value, msg.options || {});
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.FIND_RESULT,
        ref,
        strategy: msg.strategy,
        value: msg.value,
      });
    }

    // 浏览器控制：执行交互
    if (msg.type === INTERNAL_MSG.EXECUTE_INTERACTION) {
      const result = executeInteraction(msg.ref, msg.action, msg.value);
      chrome.runtime.sendMessage({
        type: INTERNAL_MSG.INTERACTION_RESULT,
        ...result,
        ref: msg.ref,
        action: msg.action,
      });
    }
  });

  // -----------------------------------------------------------------------
  // 事件发送
  // -----------------------------------------------------------------------
  function sendPageEvent(event: PageEvent): void {
    if (!monitoringEnabled && !recordingMode) return;
    chrome.runtime.sendMessage({
      type: INTERNAL_MSG.PAGE_EVENT,
      event,
    });
  }

  // -----------------------------------------------------------------------
  // 点击事件
  // -----------------------------------------------------------------------
  document.addEventListener(
    "click",
    (e) => {
      const target = e.target as HTMLElement;
      const selector = getSelector(target);
      const now = Date.now();

      // 监控模式：发送事件
      sendPageEvent({
        event_type: "click",
        timestamp: now,
        target: selector,
      });

      // 录制模式：记录步骤 + 实时上报
      if (recordingMode) {
        const step = {
          action: "click" as const,
          selector,
          description: `点击 ${getElementDescription(target)}`,
          timestamp: now,
        };
        recordedSteps.push(step);
        // 实时上报到后端
        chrome.runtime.sendMessage({
          type: "qiuwen:flow_step",
          step,
        });
      }

      // 困惑检测：连续点击同一元素
      if (selector === lastClickTarget && now - lastClickTime < CONFUSION_WINDOW) {
        clickCount++;
        if (clickCount >= CONFUSION_THRESHOLD) {
          // 发送困惑提示
          chrome.runtime.sendMessage({
            type: "qiuwen:user_confused",
            selector,
            clickCount,
            message: `检测到你连续点击了 ${clickCount} 次，需要帮助吗？`,
          });
          clickCount = 0;
        }
      } else {
        clickCount = 1;
      }
      lastClickTarget = selector;
      lastClickTime = now;
    },
    true
  );

  // -----------------------------------------------------------------------
  // 输入事件
  // -----------------------------------------------------------------------
  document.addEventListener(
    "input",
    (e) => {
      const target = e.target as HTMLElement;

      // 隐私保护：密码字段不采集
      if (isPasswordField(target)) return;

      const selector = getSelector(target);
      const value = target instanceof HTMLInputElement ? target.value : "";

      // 脱敏
      const safeValue = sanitizeText(value);

      sendPageEvent({
        event_type: "input",
        timestamp: Date.now(),
        target: selector,
        value: safeValue,
      });

      // 录制模式：记录 + 实时上报
      if (recordingMode && safeValue) {
        const step = {
          action: "input" as const,
          selector,
          description: `在输入框中输入内容`,
          value: safeValue,
          timestamp: Date.now(),
        };
        recordedSteps.push(step);
        chrome.runtime.sendMessage({
          type: "qiuwen:flow_step",
          step,
        });
      }
    },
    true
  );

  // -----------------------------------------------------------------------
  // SPA 路由变化
  // -----------------------------------------------------------------------
  let lastUrl = window.location.href;

  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({
        event_type: "route_change",
        timestamp: Date.now(),
        url: lastUrl,
      });

      // 录制模式：记录 + 实时上报
      if (recordingMode) {
        const step = {
          action: "navigate" as const,
          selector: "",
          description: `导航到 ${lastUrl}`,
          timestamp: Date.now(),
        };
        recordedSteps.push(step);
        chrome.runtime.sendMessage({
          type: "qiuwen:flow_step",
          step,
        });
      }
    }
  });
  urlObserver.observe(document.body, { childList: true, subtree: true });

  // 拦截 pushState / replaceState
  const origPush = history.pushState;
  const origReplace = history.replaceState;

  history.pushState = function (...args) {
    origPush.apply(this, args);
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({ event_type: "route_change", timestamp: Date.now(), url: lastUrl });
    }
  };

  history.replaceState = function (...args) {
    origReplace.apply(this, args);
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({ event_type: "route_change", timestamp: Date.now(), url: lastUrl });
    }
  };

  // -----------------------------------------------------------------------
  // 辅助函数
  // -----------------------------------------------------------------------

  /**
   * 生成元素 CSS 选择器。
   */
  function getSelector(el: HTMLElement): string {
    if (el.id) return `#${el.id}`;
    if (el.className && typeof el.className === "string") {
      const classes = el.className.trim().split(/\s+/).slice(0, 3).join(".");
      if (classes) return `${el.tagName.toLowerCase()}.${classes}`;
    }
    return el.tagName.toLowerCase();
  }

  /**
   * 获取元素的可读描述。
   */
  function getElementDescription(el: HTMLElement): string {
    // 优先使用文本内容
    const text = el.textContent?.trim().slice(0, 20);
    if (text) return text;

    // 使用 aria-label
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel;

    // 使用 placeholder
    const placeholder = el.getAttribute("placeholder");
    if (placeholder) return placeholder;

    // 使用标签名
    return el.tagName.toLowerCase();
  }
});
