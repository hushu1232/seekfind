/**
 * 求问 — Content Script: 隐私脱敏模块
 * =====================================
 *
 * 职责：
 *   - 对页面采集的数据进行隐私保护处理
 *   - 密码字段不采集
 *   - 邮箱、手机号、Token 等敏感信息自动替换为占位符
 *
 * 脱敏规则：
 *   邮箱    → [邮箱]
 *   手机号  → [手机号]
 *   密码    → [已脱敏]
 *   Token   → [已脱敏]
 *   URL 参数中 token/key/password → [已脱敏]
 *
 * 使用：
 *   import { sanitizeText, sanitizeUrl, isPasswordField } from "./privacy";
 *   const safe = sanitizeText("我的邮箱是 test@example.com");
 *   // "我的邮箱是 [邮箱]"
 */

// ---------------------------------------------------------------------------
// 文本脱敏
// ---------------------------------------------------------------------------

/**
 * 邮箱地址脱敏。
 * 匹配标准邮箱格式，替换为 [邮箱]。
 */
function sanitizeEmail(text: string): string {
  return text.replace(
    /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
    "[邮箱]"
  );
}

/**
 * 中国大陆手机号脱敏。
 * 匹配 1 开头的 11 位手机号，替换为 [手机号]。
 */
function sanitizePhone(text: string): string {
  return text.replace(/1[3-9]\d{9}/g, "[手机号]");
}

/**
 * 密码/密钥/Token 脱敏。
 * 匹配常见的密钥模式，替换值部分为 [已脱敏]。
 */
function sanitizeSecrets(text: string): string {
  return text
    .replace(/password[=:]\s*\S+/gi, "password=[已脱敏]")
    .replace(/token[=:]\s*\S+/gi, "token=[已脱敏]")
    .replace(/secret[=:]\s*\S+/gi, "secret=[已脱敏]")
    .replace(/api[_-]?key[=:]\s*\S+/gi, "api_key=[已脱敏]");
}

// ---------------------------------------------------------------------------
// URL 脱敏
// ---------------------------------------------------------------------------

/**
 * URL 参数脱敏。
 * 将 URL 中的敏感查询参数（token/key/password 等）替换为 [已脱敏]。
 *
 * 示例：
 *   sanitizeUrl("https://example.com?token=abc123&name=test")
 *   → "https://example.com?token=[已脱敏]&name=test"
 */
export function sanitizeUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const sensitiveParams = [
      "token",
      "key",
      "password",
      "secret",
      "access_token",
      "refresh_token",
      "api_key",
    ];
    for (const param of sensitiveParams) {
      if (parsed.searchParams.has(param)) {
        parsed.searchParams.set(param, "[已脱敏]");
      }
    }
    return parsed.toString();
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// 元素检测
// ---------------------------------------------------------------------------

/**
 * 检查元素是否为密码输入字段。
 *
 * 用途：密码字段的值不应被采集或记录。
 */
export function isPasswordField(el: HTMLElement): boolean {
  if (el instanceof HTMLInputElement) {
    return el.type === "password";
  }
  return false;
}

// ---------------------------------------------------------------------------
// 组合脱敏
// ---------------------------------------------------------------------------

/**
 * 对文本执行全量脱敏。
 * 依次应用：邮箱 → 手机号 → 密钥
 *
 * @param text 原始文本
 * @returns 脱敏后的文本
 */
export function sanitizeText(text: string): string {
  let result = text;
  result = sanitizeEmail(result);
  result = sanitizePhone(result);
  result = sanitizeSecrets(result);
  return result;
}
