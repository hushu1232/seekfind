/**
 * 求问 — Content Script: 隐私脱敏
 * 对页面采集的数据进行隐私保护处理。
 */

// ---------------------------------------------------------------------------
// 脱敏规则
// ---------------------------------------------------------------------------

/** 邮箱脱敏 */
function sanitizeEmail(text: string): string {
  return text.replace(
    /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
    "[邮箱]"
  );
}

/** 手机号脱敏 */
function sanitizePhone(text: string): string {
  return text.replace(
    /1[3-9]\d{9}/g,
    "[手机号]"
  );
}

/** 密码/Token 脱敏 */
function sanitizeSecrets(text: string): string {
  return text
    .replace(/password[=:]\s*\S+/gi, "password=[已脱敏]")
    .replace(/token[=:]\s*\S+/gi, "token=[已脱敏]")
    .replace(/secret[=:]\s*\S+/gi, "secret=[已脱敏]")
    .replace(/api[_-]?key[=:]\s*\S+/gi, "api_key=[已脱敏]");
}

/** URL 参数脱敏 */
function sanitizeUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const sensitiveParams = ["token", "key", "password", "secret", "access_token"];
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

/** 检查元素是否为密码字段 */
function isPasswordField(el: HTMLElement): boolean {
  if (el instanceof HTMLInputElement) {
    return el.type === "password";
  }
  return false;
}

// ---------------------------------------------------------------------------
// 导出脱敏函数
// ---------------------------------------------------------------------------

export function sanitizeText(text: string): string {
  let result = text;
  result = sanitizeEmail(result);
  result = sanitizePhone(result);
  result = sanitizeSecrets(result);
  return result;
}

export { sanitizeUrl, isPasswordField };
