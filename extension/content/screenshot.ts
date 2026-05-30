/**
 * 求问 — Content Script: 截图模块
 * =================================
 *
 * 职责：
 *   - 捕获当前标签页截图（chrome.tabs.captureVisibleTab）
 *   - 将截图发送到后端进行视觉定位或标注
 *
 * 注意：
 *   captureVisibleTab 只能在 Service Worker 中调用（需要 tabs 权限），
 *   Content Script 通过消息请求 Service Worker 执行截图。
 *
 * 用法：
 *   // 在需要截图时，向 Service Worker 发送请求
 *   chrome.runtime.sendMessage({ type: INTERNAL_MSG.CAPTURE_TAB }, (response) => {
 *     const imageBase64 = response.image; // data:image/png;base64,...
 *   });
 */

import { INTERNAL_MSG } from "../common/constants";

/**
 * 请求截图。
 *
 * 通过 chrome.runtime.sendMessage 请求 Service Worker 截图。
 * Service Worker 调用 chrome.tabs.captureVisibleTab 并返回 base64 图片。
 *
 * @returns Promise<string> 截图的 data URL（data:image/png;base64,...）
 */
export async function requestScreenshot(): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: INTERNAL_MSG.CAPTURE_TAB },
      (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (response?.image) {
          resolve(response.image);
        } else {
          reject(new Error("截图失败：无返回数据"));
        }
      }
    );
  });
}

/**
 * 将 data URL 转为纯 base64。
 *
 * @param dataUrl "data:image/png;base64,iVBOR..."
 * @returns "iVBOR..."
 */
export function dataUrlToBase64(dataUrl: string): string {
  if (dataUrl.startsWith("data:")) {
    return dataUrl.split(",", 1)[1] || dataUrl;
  }
  return dataUrl;
}
