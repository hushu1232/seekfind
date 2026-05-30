# agent-browser 分析与能力获取

> 基于 [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) (⭐ 34K+) 分析，提取可融入求问的核心能力。

---

## 一、agent-browser 架构解析

### 1.1 项目定位

agent-browser 是一个**为 AI Agent 设计的浏览器自动化 CLI 工具**，核心卖点：
- **无障碍树快照**：用 `@eN` 引用代替 CSS 选择器，AI 只需 ~200-400 token 理解页面
- **CDP 直连**：通过 Chrome DevTools Protocol 控制浏览器，无 Playwright/Puppeteer 依赖
- **Rust 实现**：高性能 CLI，启动快、内存低
- **会话持久化**：浏览器跨命令保持运行，支持状态保存/恢复

### 1.2 核心架构

```
agent-browser (Rust CLI)
├── cli/src/main.rs              # 入口
├── cli/src/native/
│   ├── browser.rs               # 浏览器生命周期管理
│   ├── snapshot.rs              # 无障碍树快照（核心）
│   ├── actions.rs               # 动作执行（click/fill/type/scroll）
│   ├── element.rs               # @eN 引用解析
│   ├── interaction.rs           # 交互逻辑
│   ├── screenshot.rs            # 截图
│   ├── recording.rs             # 视频录制
│   ├── state.rs                 # 状态保存/恢复
│   ├── cookies.rs               # Cookie 管理
│   ├── storage.rs               # localStorage 管理
│   ├── network.rs               # 网络拦截/Mock
│   ├── diff.rs                  # 页面变化检测
│   ├── policy.rs                # 操作确认策略
│   ├── cdp/
│   │   ├── chrome.rs            # Chrome 进程管理
│   │   ├── client.rs            # CDP WebSocket 客户端
│   │   ├── types.rs             # CDP 类型定义
│   │   └── discovery.rs         # 浏览器发现
│   ├── react/                   # React DevTools 集成
│   │   ├── tree.rs              # React 组件树
│   │   ├── renders.rs           # 渲染分析
│   │   └── vitals.rs            # 性能指标
│   └── stream/                  # 流式输出
│       ├── cdp_loop.rs          # CDP 事件循环
│       ├── chat.rs              # 聊天流
│       └── dashboard.rs         # 仪表盘流
└── packages/dashboard/          # Web 仪表盘 (Next.js)
```

### 1.3 六大核心能力

| 能力 | agent-browser 实现 | 求问可借鉴点 |
|------|-------------------|-------------|
| **无障碍树快照** | `snapshot -i` 输出 `@eN` 引用的元素树 | 比 DOM 更适合 AI 理解 |
| **@eN 引用系统** | 每次快照分配临时引用，操作后刷新 | 替代 CSS 选择器的 AI 友好方案 |
| **语义定位器** | `find role/text/label/placeholder` | 比 CSS 选择器更健壮 |
| **会话持久化** | `state save/restore` + `--session-name` | 跨命令保持登录状态 |
| **网络拦截** | `network route` Mock API 响应 | 测试/调试用 |
| **页面变化检测** | `diff` 命令对比前后快照 | 检测操作结果 |

---

## 二、可获取的核心能力

### 能力 1: 无障碍树快照（替代 DOM 快照）

**agent-browser 的做法：**
```bash
agent-browser snapshot -i
# 输出：
# @e1 [heading] "Log in"
# @e2 [form]
#   @e3 [input type="email"] placeholder="Email"
#   @e4 [input type="password"] placeholder="Password"
#   @e5 [button type="submit"] "Continue"
```

**为什么比 DOM 好：**
- 只保留语义信息（角色、名称、状态），去掉 HTML 噪音
- 交互元素用 `@eN` 标记，AI 可直接引用
- ~200-400 token vs DOM 的 ~5000+ token
- 自动过滤不可见元素

**求问的现状：**
- `classify_page.py` 用 DOM 快照的前 2000 字符
- `highlight_element.py` 用 CSS 选择器
- 没有无障碍树能力

**获取方案：**
通过 CDP 的 `Accessibility.getFullAXTree` 命令获取无障碍树，实现 Python 版快照。

### 能力 2: @eN 引用系统（替代 CSS 选择器）

**agent-browser 的做法：**
- 每次 `snapshot` 重新分配 `@e1, @e2, ...`
- 引用在页面变化后失效，强制重新快照
- 操作命令用 `@eN` 而非 CSS 选择器

**为什么比 CSS 选择器好：**
- AI 不需要学习 CSS 语法
- 引用是确定性的（不依赖页面结构）
- 引用失效是明确的（不是静默失败）

**求问的现状：**
- LLM 推理出 CSS 选择器，可能不准确
- 指纹库存储 CSS 选择器，页面改版即失效

**获取方案：**
在快照模块中实现 `@eN` 引用分配，操作模块用引用解析到实际元素。

### 能力 3: 语义定位器（比 CSS 更健壮）

**agent-browser 的做法：**
```bash
agent-browser find role button click --name "Submit"
agent-browser find text "Sign In" click
agent-browser find label "Email" fill "user@test.com"
agent-browser find placeholder "Search" type "query"
```

**为什么比 CSS 选择器健壮：**
- 基于无障碍树的语义属性，不依赖 DOM 结构
- 页面改版后只要按钮文字不变，定位仍然有效
- 更接近人类的定位方式

**获取方案：**
在 CDP 客户端中实现 `find_role`, `find_text`, `find_label` 等语义查询。

### 能力 4: 页面变化检测

**agent-browser 的做法：**
```bash
agent-browser diff  # 对比前后快照，输出变化
```

**用途：**
- 检测点击后页面是否变化
- 检测表单提交是否成功
- 检测导航是否完成

**获取方案：**
保存前一次快照的哈希，与新快照对比。

---

## 三、技术实现方案

### 3.1 CDP 客户端（Python）

**新建文件：`backend/browser/cdp_client.py`**

通过 WebSocket 连接 Chrome 的 CDP 端口，发送命令和接收事件。

```python
"""
求问 — CDP 客户端
=================

通过 Chrome DevTools Protocol 控制浏览器。

核心能力：
  - 获取无障碍树快照（Accessibility.getFullAXTree）
  - 执行 JavaScript（Runtime.evaluate）
  - 截图（Page.captureScreenshot）
  - 导航（Page.navigate）
  - 元素交互（DOM.querySelector + DOM.focus + Input.dispatchKeyEvent）

依赖：websockets（已有）
"""

import asyncio
import json
import websockets

class CDPClient:
    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws = None
        self._msg_id = 0

    async def connect(self):
        self._ws = await websockets.connect(self._ws_url)

    async def send(self, method: str, params: dict = None) -> dict:
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        await self._ws.send(json.dumps(msg))
        # 等待对应 ID 的响应
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("id") == self._msg_id:
                return resp.get("result", {})

    async def get_full_ax_tree(self) -> list:
        """获取完整无障碍树。"""
        result = await self.send("Accessibility.getFullAXTree")
        return result.get("nodes", [])

    async def navigate(self, url: str):
        """导航到 URL。"""
        await self.send("Page.navigate", {"url": url})

    async def screenshot(self, format: str = "png") -> str:
        """截图，返回 base64。"""
        result = await self.send("Page.captureScreenshot", {"format": format})
        return result.get("data", "")

    async def evaluate(self, expression: str) -> any:
        """执行 JavaScript。"""
        result = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        return result.get("result", {}).get("value")
```

### 3.2 无障碍树快照器

**新建文件：`backend/browser/snapshot.py`**

```python
"""
求问 — 无障碍树快照器
====================

参考 agent-browser 的 snapshot.rs 实现。

将 CDP 无障碍树转换为紧凑的文本格式：
  @e1 [heading] "Log in"
  @e2 [form]
    @e3 [input type="email"] placeholder="Email"
    @e4 [button type="submit"] "Continue"

交互元素角色：button, link, textbox, checkbox, radio, combobox, ...
内容角色：heading, cell, listitem, article, ...
结构角色：generic, group, list, table, ...
"""

# 交互元素角色（参考 agent-browser snapshot.rs）
INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox",
    "listbox", "menuitem", "option", "searchbox", "slider", "tab",
}

CONTENT_ROLES = {
    "heading", "cell", "listitem", "article", "region", "main",
}

class SnapshotNode:
    def __init__(self, ax_node: dict):
        self.role = ax_node.get("role", {}).get("value", "generic")
        self.name = ax_node.get("name", {}).get("value", "")
        self.node_id = ax_node.get("nodeId", "")
        self.backend_node_id = ax_node.get("backendDOMNodeId")
        self.children = ax_node.get("childIds", [])
        self.properties = self._parse_properties(ax_node.get("properties", []))
        self.ref_id = None  # @eN

    def _parse_properties(self, properties: list) -> dict:
        result = {}
        for prop in properties:
            name = prop.get("name", "")
            value = prop.get("value", {}).get("value", "")
            result[name] = value
        return result

    @property
    def is_interactive(self) -> bool:
        return self.role in INTERACTIVE_ROLES

    @property
    def is_content(self) -> bool:
        return self.role in CONTENT_ROLES

def build_snapshot(nodes: list[dict], interactive_only: bool = False) -> str:
    """将无障碍树节点列表转换为快照文本。"""
    # 构建节点映射
    node_map = {}
    roots = []
    for ax_node in nodes:
        node = SnapshotNode(ax_node)
        node_map[node.node_id] = node

    # 构建父子关系
    for node in node_map.values():
        for child_id in node.children:
            if child_id in node_map:
                node_map[child_id].parent = node

    # 找根节点
    for node in node_map.values():
        if not hasattr(node, 'parent'):
            roots.append(node)

    # 分配 @eN 引用
    ref_counter = [0]
    def assign_refs(node, depth=0):
        if not interactive_only or node.is_interactive or node.is_content:
            ref_counter[0] += 1
            node.ref_id = f"@e{ref_counter[0]}"
        for child_id in node.children:
            if child_id in node_map:
                assign_refs(node_map[child_id], depth + 1)

    for root in roots:
        assign_refs(root)

    # 生成文本
    lines = []
    def render(node, depth=0):
        if interactive_only and not node.is_interactive and not node.is_content:
            # 跳过非交互节点，但继续遍历子节点
            for child_id in node.children:
                if child_id in node_map:
                    render(node_map[child_id], depth)
            return

        indent = "  " * depth
        ref = node.ref_id or ""
        role = node.role
        name = f' "{node.name}"' if node.name else ""
        line = f"{indent}{ref} [{role}]{name}"
        lines.append(line)

        for child_id in node.children:
            if child_id in node_map:
                render(node_map[child_id], depth + 1)

    for root in roots:
        render(root)

    return "\n".join(lines)
```

### 3.3 语义定位器

**新建文件：`backend/browser/locator.py`**

```python
"""
求问 — 语义定位器
================

参考 agent-browser 的 find 命令。

提供基于无障碍树的语义定位：
  - find_role("button", name="Submit") → CSS 选择器
  - find_text("Sign In") → CSS 选择器
  - find_label("Email") → CSS 选择器
"""

class SemanticLocator:
    def __init__(self, cdp_client):
        self._cdp = cdp_client

    async def find_role(self, role: str, name: str = None) -> str | None:
        """按角色+名称查找元素，返回后端节点 ID。"""
        nodes = await self._cdp.get_full_ax_tree()
        for node in nodes:
            node_role = node.get("role", {}).get("value", "")
            node_name = node.get("name", {}).get("value", "")
            if node_role == role:
                if name is None or node_name == name:
                    return node.get("backendDOMNodeId")
        return None

    async def find_text(self, text: str, exact: bool = False) -> str | None:
        """按文本内容查找元素。"""
        nodes = await self._cdp.get_full_ax_tree()
        for node in nodes:
            node_name = node.get("name", {}).get("value", "")
            if exact:
                if node_name == text:
                    return node.get("backendDOMNodeId")
            else:
                if text in node_name:
                    return node.get("backendDOMNodeId")
        return None
```

---

## 四、集成到求问的方案

### 4.1 新增浏览器控制模块

```
backend/browser/
├── __init__.py
├── cdp_client.py        # CDP WebSocket 客户端
├── snapshot.py          # 无障碍树快照器
├── locator.py           # 语义定位器
└── controller.py        # 浏览器控制器（封装高级操作）
```

### 4.2 新增 Agent 工具

| 工具 | 说明 | 替代 |
|------|------|------|
| `browser_snapshot` | 获取页面无障碍树快照 | classify_page 的 DOM 快照 |
| `browser_navigate` | 导航到 URL | fetch_doc_page 的部分功能 |
| `browser_click` | 点击元素（用 @eN 或语义定位） | highlight_element 的扩展 |
| `browser_fill` | 填写表单 | 新增能力 |
| `browser_screenshot` | 截图 | 已有，增强标注 |

### 4.3 改造 highlight_element

**现有流程：**
```
LLM 推理 CSS 选择器 → highlight_element → 前端高亮
```

**强化后流程：**
```
LLM 推理语义描述 → browser_snapshot 获取 @eN 引用
                  → 语义定位器匹配 → 前端高亮
```

### 4.4 MCP 工具扩展

在 MCP Server 中新增浏览器控制工具：

```python
@mcp.tool()
async def browser_snapshot(url: str, interactive: bool = True) -> str:
    """获取页面的无障碍树快照（@eN 引用格式）。"""
    ...

@mcp.tool()
async def browser_navigate(url: str) -> str:
    """导航浏览器到指定 URL。"""
    ...

@mcp.tool()
async def browser_interact(ref: str, action: str, value: str = "") -> str:
    """与页面元素交互（click/fill/type）。"""
    ...
```

---

## 五、与 Scrapling 的互补关系

| 维度 | Scrapling | agent-browser | 求问现状 |
|------|-----------|---------------|---------|
| **页面获取** | HTTP + 浏览器 + 隐身 | CDP 直连 | Scrapling Fetcher |
| **元素定位** | CSS/XPath + 指纹存储 | 无障碍树 + @eN 引用 | CSS + 指纹 |
| **AI 友好度** | 中（需 CSS 知识） | 高（@eN + 语义定位） | 中 |
| **交互能力** | 无（只抓取） | 完整（click/fill/scroll） | 无 |
| **适用场景** | 离线文档索引 | 实时页面交互 | 离线为主 |

**互补方案：**
- Scrapling → 离线文档爬取（已有）
- agent-browser 能力 → 实时页面交互 + AI 友好快照（新增）

---

## 六、实施路线

### Sprint 7: 浏览器控制能力

| 任务 | 优先级 | 工时 | 说明 | 状态 |
|------|--------|------|------|------|
| T24: 无障碍树快照模块 | P0 | 4h | Content Script DOM 遍历 + @eN 引用 | ✅ |
| T25: 语义定位器 | P0 | 3h | find_role/text/label/placeholder/testid | ✅ (T24 一并完成) |
| T26: 浏览器交互工具 | P1 | 4h | browser_snapshot/interact/find Agent 工具 | ✅ |
| T27: MCP 浏览器工具 | P2 | 2h | MCP Server 新增 3 个浏览器工具 | ✅ |

**总预估：13h · 实际完成：✅**

### 适配说明

与 agent-browser 的关键差异：
- agent-browser: Rust CLI + CDP 直连 Chrome
- 求问: TypeScript Content Script + Chrome Extension 原生 DOM 访问

优势：
- 无需安装额外依赖（不需要 CDP WebSocket 客户端）
- 利用 Chrome Extension 原生能力，更轻量
- Content Script 直接访问 DOM，无需 CDP 协议开销

---

## 七、依赖变更

```txt
# CDP WebSocket 客户端
websockets>=12.0
```

无需安装 Playwright/Puppeteer — 直接通过 CDP 协议控制已安装的 Chrome。
