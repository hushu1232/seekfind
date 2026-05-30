/**
 * 求问 — Content Script: DOM 观察者
 * 负责页面感知、事件采集、页面就绪上报。
 */

import { INTERNAL_MSG } from "../common/constants";
import type { PageEvent } from "../common/types";
import { injectAtStart } from "../common/browser-compat";

injectAtStart(() => {
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
  // 事件采集（Phase 3 完整实现，当前为基础骨架）
  // -----------------------------------------------------------------------
  let monitoringEnabled = false;

  // 监听来自 Service Worker 的控制消息
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "qiuwen:enable_monitoring") {
      monitoringEnabled = true;
    }
    if (msg.type === "qiuwen:disable_monitoring") {
      monitoringEnabled = false;
    }
  });

  // 基础事件采集
  function sendPageEvent(event: PageEvent): void {
    if (!monitoringEnabled) return;
    chrome.runtime.sendMessage({
      type: INTERNAL_MSG.PAGE_EVENT,
      event,
    });
  }

  // 点击事件
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    sendPageEvent({
      event_type: "click",
      timestamp: Date.now(),
      target: getSelector(target),
    });
  }, true);

  // URL 变化（SPA 路由）
  let lastUrl = window.location.href;
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

  // -----------------------------------------------------------------------
  // 辅助函数
  // -----------------------------------------------------------------------
  function getSelector(el: HTMLElement): string {
    if (el.id) return `#${el.id}`;
    if (el.className && typeof el.className === "string") {
      const classes = el.className.trim().split(/\s+/).slice(0, 3).join(".");
      if (classes) return `${el.tagName.toLowerCase()}.${classes}`;
    }
    return el.tagName.toLowerCase();
  }
});
