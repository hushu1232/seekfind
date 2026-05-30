/**
 * 求问 — Content Script: 无障碍树快照
 * ====================================
 *
 * 参考 agent-browser 的 snapshot.rs 实现，
 * 适配 Chrome Extension 原生架构（直接 DOM 遍历，不依赖 CDP）。
 *
 * 核心能力：
 *   1. DOM → 无障碍树快照（紧凑文本格式）
 *   2. @eN 引用系统（data-qw-ref 属性）
 *   3. 语义定位器（find_role / find_text / find_label）
 *
 * 输出格式（参考 agent-browser）：
 *   @e1 [heading] "Log in"
 *   @e2 [form]
 *     @e3 [textbox] placeholder="Email"
 *     @e4 [textbox] placeholder="Password"
 *     @e5 [button] "Continue"
 *
 * 交互元素角色：button, link, textbox, checkbox, radio, combobox, ...
 * 内容角色：heading, listitem, img, ...
 * 结构角色：form, navigation, main, table, ...
 */

// ---------------------------------------------------------------------------
// 角色分类（参考 agent-browser snapshot.rs）
// ---------------------------------------------------------------------------

/** 交互元素角色 — 分配 @eN 引用，AI 可直接操作 */
const INTERACTIVE_ROLES = new Set([
  "button", "link", "textbox", "checkbox", "radio", "combobox",
  "listbox", "menuitem", "menuitemcheckbox", "menuitemradio",
  "option", "searchbox", "slider", "spinbutton", "switch",
  "tab", "treeitem",
]);

/** 内容角色 — 分配 @eN 引用，AI 可读取 */
const CONTENT_ROLES = new Set([
  "heading", "img", "listitem", "article", "region", "main",
  "cell", "gridcell", "columnheader", "rowheader",
]);

/** 结构角色 — 不分配引用，但保留层级 */
const STRUCTURAL_ROLES = new Set([
  "form", "navigation", "toolbar", "dialog", "alertdialog",
  "table", "list", "row", "rowgroup", "grid", "tablist",
  "menu", "menubar", "tree", "group", "separator",
]);

/** 应跳过的角色 */
const SKIP_ROLES = new Set([
  "none", "presentation", "generic", "script", "style",
]);

// ---------------------------------------------------------------------------
// 快照节点
// ---------------------------------------------------------------------------

interface SnapshotNode {
  role: string;
  name: string;
  element: HTMLElement;
  refId: string | null;
  depth: number;
  children: SnapshotNode[];
  // 元素属性
  tag: string;
  inputType?: string;
  placeholder?: string;
  href?: string;
  checked?: boolean;
  expanded?: boolean;
  selected?: boolean;
  disabled?: boolean;
  value?: string;
  level?: number; // heading level
}

// ---------------------------------------------------------------------------
// @eN 引用存储
// ---------------------------------------------------------------------------

/** ref → element 映射表 */
const refMap = new Map<string, HTMLElement>();
let refCounter = 0;

/** 清空引用表（每次快照前调用） */
function clearRefs(): void {
  // 移除旧的 data-qw-ref 属性
  refMap.forEach((el) => {
    el.removeAttribute("data-qw-ref");
  });
  refMap.clear();
  refCounter = 0;
}

/** 分配 @eN 引用 */
function assignRef(element: HTMLElement): string {
  refCounter++;
  const ref = `@e${refCounter}`;
  refMap.set(ref, element);
  element.setAttribute("data-qw-ref", ref);
  return ref;
}

/** 通过 @eN 获取元素 */
export function getElementByRef(ref: string): HTMLElement | null {
  return refMap.get(ref) || null;
}

// ---------------------------------------------------------------------------
// 角色推断
// ---------------------------------------------------------------------------

/**
 * 从元素推断无障碍角色。
 *
 * 优先级：
 *   1. 显式 ARIA role 属性
 *   2. HTML 语义标签隐含的角色
 *   3. 默认 "generic"
 */
function inferRole(el: HTMLElement): string {
  // 显式 ARIA role
  const explicitRole = el.getAttribute("role");
  if (explicitRole) return explicitRole;

  const tag = el.tagName.toLowerCase();

  // HTML 语义标签 → 角色映射
  switch (tag) {
    case "a":
      return el.hasAttribute("href") ? "link" : "generic";
    case "button":
      return "button";
    case "input":
      return inferInputRole(el as HTMLInputElement);
    case "select":
      return "combobox";
    case "textarea":
      return "textbox";
    case "h1": case "h2": case "h3": case "h4": case "h5": case "h6":
      return "heading";
    case "img":
      return "img";
    case "table":
      return "table";
    case "tr":
      return "row";
    case "td": case "th":
      return "cell";
    case "ul": case "ol":
      return "list";
    case "li":
      return "listitem";
    case "nav":
      return "navigation";
    case "main":
      return "main";
    case "form":
      return "form";
    case "dialog":
      return "dialog";
    case "label":
      return "label";
    case "fieldset":
      return "group";
    case "legend":
      return "legend";
    case "section":
      return "region";
    case "article":
      return "article";
    case "aside":
      return "complementary";
    case "header":
      return "banner";
    case "footer":
      return "contentinfo";
    default:
      return "generic";
  }
}

function inferInputRole(input: HTMLInputElement): string {
  const type = (input.type || "text").toLowerCase();
  switch (type) {
    case "button": case "submit": case "reset": case "image":
      return "button";
    case "checkbox":
      return "checkbox";
    case "radio":
      return "radio";
    case "range":
      return "slider";
    case "number":
      return "spinbutton";
    case "search":
      return "searchbox";
    case "email": case "password": case "tel": case "url": case "text":
    default:
      return "textbox";
  }
}

// ---------------------------------------------------------------------------
// 名称计算
// ---------------------------------------------------------------------------

/**
 * 计算元素的无障碍名称。
 *
 * 参考 WAI-ARIA Accessible Name computation:
 *   1. aria-labelledby
 *   2. aria-label
 *   3. <label for="...">
 *   4. title 属性
 *   5. placeholder（input/textarea）
 *   6. alt（img）
 *   7. 可见文本内容（截断到 50 字符）
 */
function computeAccessibleName(el: HTMLElement): string {
  // aria-labelledby
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const names = labelledBy.split(/\s+/).map(id => {
      const ref = document.getElementById(id);
      return ref ? ref.textContent?.trim() || "" : "";
    }).filter(Boolean);
    if (names.length > 0) return names.join(" ");
  }

  // aria-label
  const ariaLabel = el.getAttribute("aria-label");
  if (ariaLabel) return ariaLabel;

  // <label for="">
  if (el.id) {
    const label = document.querySelector(`label[for="${el.id}"]`);
    if (label) return label.textContent?.trim() || "";
  }

  // title
  const title = el.getAttribute("title");
  if (title) return title;

  // placeholder
  const placeholder = el.getAttribute("placeholder");
  if (placeholder) return placeholder;

  // alt (img)
  const alt = el.getAttribute("alt");
  if (alt) return alt;

  // 可见文本内容
  const text = getDirectText(el);
  if (text) return text.slice(0, 50);

  return "";
}

/**
 * 获取元素的直接文本内容（不包含子元素的文本）。
 */
function getDirectText(el: HTMLElement): string {
  let text = "";
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      text += node.textContent || "";
    }
  }
  return text.trim();
}

// ---------------------------------------------------------------------------
// 可见性检查
// ---------------------------------------------------------------------------

function isVisible(el: HTMLElement): boolean {
  if (el.hidden) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none") return false;
  if (style.visibility === "hidden") return false;
  if (style.opacity === "0") return false;
  // 检查尺寸（排除 0x0 元素）
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  return true;
}

// ---------------------------------------------------------------------------
// DOM 遍历 → 快照树
// ---------------------------------------------------------------------------

/**
 * 遍历 DOM 构建快照树。
 *
 * 跳过不可见元素和应忽略的角色。
 * 为交互/内容元素分配 @eN 引用。
 */
function buildSnapshotTree(
  root: HTMLElement,
  depth: number = 0,
  maxDepth: number = 15,
): SnapshotNode | null {
  if (depth > maxDepth) return null;
  if (!isVisible(root)) return null;

  const role = inferRole(root);
  if (SKIP_ROLES.has(role)) {
    // 跳过自身，但继续遍历子节点
    const children: SnapshotNode[] = [];
    for (const child of root.children) {
      if (child instanceof HTMLElement) {
        const node = buildSnapshotTree(child, depth, maxDepth);
        if (node) children.push(node);
      }
    }
    if (children.length === 0) return null;
    if (children.length === 1) return children[0];
    return {
      role: "group",
      name: "",
      element: root,
      refId: null,
      depth,
      children,
      tag: root.tagName.toLowerCase(),
    };
  }

  const node: SnapshotNode = {
    role,
    name: computeAccessibleName(root),
    element: root,
    refId: null,
    depth,
    children: [],
    tag: root.tagName.toLowerCase(),
  };

  // 提取额外属性
  if (root instanceof HTMLInputElement) {
    node.inputType = root.type;
    node.placeholder = root.placeholder;
    node.checked = root.checked;
    node.disabled = root.disabled;
    node.value = root.value;
  }
  if (root instanceof HTMLAnchorElement) {
    node.href = root.href;
  }
  if (root instanceof HTMLSelectElement) {
    node.disabled = root.disabled;
  }
  if (root instanceof HTMLTextAreaElement) {
    node.placeholder = root.placeholder;
    node.disabled = root.disabled;
  }
  if (role === "heading") {
    const level = parseInt(root.tagName[1] || "0");
    if (level > 0) node.level = level;
  }

  // 分配 @eN 引用（交互元素 + 内容元素）
  if (INTERACTIVE_ROLES.has(role) || CONTENT_ROLES.has(role)) {
    node.refId = assignRef(root);
  }

  // 遍历子节点
  for (const child of root.children) {
    if (child instanceof HTMLElement) {
      // 跳过求问自身的 UI 元素
      if (child.id?.startsWith("qiuwen-")) continue;

      const childNode = buildSnapshotTree(child, depth + 1, maxDepth);
      if (childNode) node.children.push(childNode);
    }
  }

  return node;
}

// ---------------------------------------------------------------------------
// 快照文本渲染
// ---------------------------------------------------------------------------

/**
 * 将快照树渲染为紧凑文本。
 */
function renderSnapshot(node: SnapshotNode, indent: number = 0): string {
  const lines: string[] = [];
  const prefix = "  ".repeat(indent);

  // 构建行
  let line = "";
  if (node.refId) {
    line += `${node.refId} `;
  }
  line += `[${node.role}]`;

  // 附加名称
  if (node.name) {
    line += ` "${node.name}"`;
  }

  // 附加属性
  const attrs: string[] = [];
  if (node.inputType && node.role === "textbox") {
    attrs.push(`type="${node.inputType}"`);
  }
  if (node.placeholder) {
    attrs.push(`placeholder="${node.placeholder}"`);
  }
  if (node.href && node.role === "link") {
    attrs.push(`href="${node.href}"`);
  }
  if (node.checked !== undefined) {
    attrs.push(`checked=${node.checked}`);
  }
  if (node.disabled) {
    attrs.push("disabled");
  }
  if (node.level) {
    attrs.push(`level=${node.level}`);
  }
  if (attrs.length > 0) {
    line += ` ${attrs.join(" ")}`;
  }

  lines.push(prefix + line);

  // 子节点
  for (const child of node.children) {
    lines.push(renderSnapshot(child, indent + 1));
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// 导出 API
// ---------------------------------------------------------------------------

export interface SnapshotOptions {
  interactiveOnly?: boolean;  // 只显示交互元素
  selector?: string;          // 限定 CSS 选择器范围
  maxDepth?: number;          // 最大深度
}

export interface SnapshotResult {
  text: string;       // 快照文本
  refCount: number;   // @eN 引用数量
  url: string;        // 当前 URL
  title: string;      // 页面标题
}

/**
 * 获取页面无障碍树快照。
 *
 * 这是 Content Script 的核心 API，供后端 Agent 工具调用。
 */
export function takeSnapshot(options: SnapshotOptions = {}): SnapshotResult {
  const {
    interactiveOnly = false,
    selector,
    maxDepth = 15,
  } = options;

  // 清空旧引用
  clearRefs();

  // 确定根元素
  let root: HTMLElement = document.body;
  if (selector) {
    const el = document.querySelector(selector);
    if (el instanceof HTMLElement) {
      root = el;
    }
  }

  // 构建快照树
  const tree = buildSnapshotTree(root, 0, maxDepth);

  if (!tree) {
    return {
      text: "(空页面)",
      refCount: 0,
      url: window.location.href,
      title: document.title,
    };
  }

  // 渲染文本
  let text = renderSnapshot(tree);

  // 交互元素过滤
  if (interactiveOnly) {
    text = filterInteractive(text);
  }

  return {
    text,
    refCount: refCounter,
    url: window.location.href,
    title: document.title,
  };
}

/**
 * 过滤只保留有 @eN 引用的行。
 */
function filterInteractive(text: string): string {
  return text
    .split("\n")
    .filter(line => line.includes("@e"))
    .join("\n");
}

// ---------------------------------------------------------------------------
// 语义定位器
// ---------------------------------------------------------------------------

export type FindStrategy = "role" | "text" | "label" | "placeholder" | "testid";

/**
 * 语义定位：按策略查找元素。
 *
 * 返回匹配元素的 @eN 引用，未找到返回 null。
 */
export function findElement(
  strategy: FindStrategy,
  value: string,
  options: { exact?: boolean; name?: string } = {},
): string | null {
  const { exact = false, name } = options;

  // 遍历所有有引用的元素
  for (const [ref, el] of refMap.entries()) {
    switch (strategy) {
      case "role": {
        const role = inferRole(el);
        if (role === value) {
          if (!name || computeAccessibleName(el) === name) {
            return ref;
          }
        }
        break;
      }
      case "text": {
        const text = el.textContent?.trim() || "";
        if (exact ? text === value : text.includes(value)) {
          return ref;
        }
        break;
      }
      case "label": {
        const label = computeAccessibleName(el);
        if (exact ? label === value : label.includes(value)) {
          return ref;
        }
        break;
      }
      case "placeholder": {
        const ph = el.getAttribute("placeholder") || "";
        if (exact ? ph === value : ph.includes(value)) {
          return ref;
        }
        break;
      }
      case "testid": {
        const testid = el.getAttribute("data-testid") || el.getAttribute("data-test-id") || "";
        if (testid === value) {
          return ref;
        }
        break;
      }
    }
  }

  return null;
}

/**
 * 执行交互操作。
 *
 * @param ref @eN 引用
 * @param action 操作类型
 * @param value 填写值（fill/type 时使用）
 */
export function executeInteraction(
  ref: string,
  action: "click" | "dblclick" | "hover" | "focus" | "fill" | "type" | "check" | "uncheck" | "select" | "scroll",
  value?: string,
): { success: boolean; error?: string } {
  const el = getElementByRef(ref);
  if (!el) {
    return { success: false, error: `元素 ${ref} 不存在` };
  }

  try {
    switch (action) {
      case "click":
        el.click();
        break;
      case "dblclick":
        el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
        break;
      case "hover":
        el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
        el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        break;
      case "focus":
        (el as HTMLElement).focus();
        break;
      case "fill":
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
          el.value = value || "";
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        break;
      case "type":
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
          el.value += value || "";
          el.dispatchEvent(new Event("input", { bubbles: true }));
        }
        break;
      case "check":
        if (el instanceof HTMLInputElement && el.type === "checkbox") {
          el.checked = true;
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        break;
      case "uncheck":
        if (el instanceof HTMLInputElement && el.type === "checkbox") {
          el.checked = false;
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        break;
      case "select":
        if (el instanceof HTMLSelectElement) {
          el.value = value || "";
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        break;
      case "scroll":
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        break;
      default:
        return { success: false, error: `未知操作: ${action}` };
    }
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}
