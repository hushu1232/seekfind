/**
 * 求问 — Content Script: DOM 观察者
 * ====================================
 *
 * 职责：
 *   1. 页面就绪上报（通知 Service Worker 当前页面 URL/标题）
 *   2. 事件采集（click / input / scroll / route_change）
 *   3. 辅助函数：生成元素 CSS 选择器
 *
 * 注入时机：
 *   manifest.json 中配置为 "document_start"，确保最早注入。
 *   但 DOM 可能还未就绪，需要等待 load/DOMContentLoaded。
 *
 * 隐私：
 *   事件采集默认关闭（monitoringEnabled = false），
 *   需要用户在设置中主动开启。
 */

import { INTERNAL_MSG } from "../common/constants";
import type { PageEvent } from "../common/types";
import { injectAtStart } from "../common/browser-compat";

/**
 * 使用浏览器兼容层注入代码。
 * Chrome/Edge 直接执行，Firefox 降级为 DOMContentLoaded。
 */
injectAtStart(() => {
  // -----------------------------------------------------------------------
  // 页面就绪上报
  // -----------------------------------------------------------------------

  /**
   * 通知 Service Worker 当前页面已就绪。
   * 携带 URL 和标题，用于后端上下文。
   */
  function notifyPageReady(): void {
    chrome.runtime.sendMessage({
      type: INTERNAL_MSG.PAGE_READY,
      url: window.location.href,
      title: document.title,
    });
  }

  // 根据文档加载状态决定上报时机
  if (document.readyState === "complete") {
    notifyPageReady();
  } else {
    window.addEventListener("load", notifyPageReady);
  }

  // -----------------------------------------------------------------------
  // 事件采集（默认关闭）
  // -----------------------------------------------------------------------

  /** 是否启用事件采集（用户在设置中开启） */
  let monitoringEnabled = false;

  // 监听 Service Worker 的控制消息
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "qiuwen:enable_monitoring") {
      monitoringEnabled = true;
      console.log("[求问] 事件采集已开启");
    }
    if (msg.type === "qiuwen:disable_monitoring") {
      monitoringEnabled = false;
      console.log("[求问] 事件采集已关闭");
    }
  });

  /**
   * 发送页面事件到 Service Worker。
   * 仅在 monitoringEnabled = true 时发送。
   */
  function sendPageEvent(event: PageEvent): void {
    if (!monitoringEnabled) return;
    chrome.runtime.sendMessage({
      type: INTERNAL_MSG.PAGE_EVENT,
      event,
    });
  }

  // --- 点击事件 ---
  document.addEventListener(
    "click",
    (e) => {
      const target = e.target as HTMLElement;
      sendPageEvent({
        event_type: "click",
        timestamp: Date.now(),
        target: getSelector(target),
      });
    },
    true // 捕获阶段，确保最早捕获
  );

  // --- SPA 路由变化 ---
  // 监听 URL 变化（pushState / replaceState / popstate）
  let lastUrl = window.location.href;

  // MutationObserver 监听 DOM 变化来检测 URL 变化
  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({
        event_type: "route_change",
        timestamp: Date.now(),
        url: lastUrl,
      });
    }
  });
  urlObserver.observe(document.body, { childList: true, subtree: true });

  // 拦截 pushState / replaceState
  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;

  history.pushState = function (...args) {
    originalPushState.apply(this, args);
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({
        event_type: "route_change",
        timestamp: Date.now(),
        url: lastUrl,
      });
    }
  };

  history.replaceState = function (...args) {
    originalReplaceState.apply(this, args);
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      sendPageEvent({
        event_type: "route_change",
        timestamp: Date.now(),
        url: lastUrl,
      });
    }
  };

  // -----------------------------------------------------------------------
  // 辅助函数
  // -----------------------------------------------------------------------

  /**
   * 为元素生成简短的 CSS 选择器。
   *
   * 优先级：
   *   1. #id（最精确）
   *   2. tag.class1.class2（较精确）
   *   3. tag（兜底）
   *
   * 注意：这是简化版本，Phase 3 的元素指纹库会提供更精确的选择器。
   */
  function getSelector(el: HTMLElement): string {
    if (el.id) return `#${el.id}`;
    if (el.className && typeof el.className === "string") {
      const classes = el.className.trim().split(/\s+/).slice(0, 3).join(".");
      if (classes) return `${el.tagName.toLowerCase()}.${classes}`;
    }
    return el.tagName.toLowerCase();
  }
});
