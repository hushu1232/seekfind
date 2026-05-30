# Sprint 6 — 新功能开发计划

> 前置条件：Sprint 1-5 全部完成，119 测试全通过。

---

## 总览

| 任务 | 优先级 | 预估工时 | 说明 | 状态 |
|------|--------|---------|------|------|
| T19: 知识库扩充 | P0 | 3h | 高频产品从 2-5 条扩充到 8-10 条 | ✅ (204 条) |
| T20: 操作流端到端打通 | P1 | 4h | 录制→存储→回放→分步指引全链路 | ✅ |
| T21: 视觉定位集成完善 | P1 | 3h | moondream2 模型加载 + 端到端测试 | ✅ |
| T22: MCP Server 集成 | P2 | 5h | 让求问成为 MCP 工具供其他 Agent 调用 | ✅ |
| T23: 离线模式完善 | P3 | 2h | edge-tts 离线降级 + 无网络提示 | ✅ |

**总预估：17h（约 2 个工作日）**

---

## T19: 知识库扩充（P0）

### 目标
高频产品从 2-5 条扩充到 8-10 条，覆盖用户最常问的操作场景。

### 当前状态
33 个产品，共约 85 条。平均每产品 2.6 条，覆盖不足。

### 扩充策略
按用户使用频率分三批：

**第一批（高频，扩充到 10 条）：**
- GitHub (5→10) — PR review、Actions 配置、Branch protection、Issues 管理、Pages 部署
- VS Code (5→10) — 调试配置、Git 集成、终端使用、插件安装、多光标编辑
- Docker (5→10) — Dockerfile 编写、Compose 网络、Volume 管理、日志查看、容器调试
- 飞书 (3→10) — 文档协作、审批流程、日历管理、云盘使用、机器人配置
- Notion (3→10) — 数据库视图、模板创建、关联属性、API 集成、权限管理

**第二批（中频，扩充到 8 条）：**
- GitLab (3→8) — CI/CD 配置、Runner 设置、Package Registry
- Jira (3→8) — 看板配置、Sprint 管理、自动化规则
- Figma (3→8) — 组件变体、Auto Layout、Dev Mode、原型交互
- 企业微信 (3→8) — 审批配置、汇报模板、微盘管理
- 钉钉 (3→8) — 智能人事、OA 审批、宜搭低代码

**第三批（低频，扩充到 6 条）：**
- 其余产品各补充 1-3 条

### 改动文件
```
backend/knowledge/builtin/github.json
backend/knowledge/builtin/vscode.json
backend/knowledge/builtin/docker.json
backend/knowledge/builtin/feishu.json
backend/knowledge/builtin/notion.json
... (共 15+ 文件)
```

### 验收标准
- 高频产品每产品 >= 10 条
- 中频产品每产品 >= 8 条
- 总条目 >= 200 条
- 每条包含 question + answer + selectors + url_pattern

---

## T20: 操作流端到端打通（P1）

### 目标
录制→存储→回放→分步指引全链路跑通。

### 当前状态
- **后端** `learn_flow.py` — start_recording / stop_recording / replay / list 四个操作已实现
- **前端** `observer.ts` — recordingMode + recordedSteps 已有录制逻辑
- **缺失** — 前端录制的步骤没有通过 WS 发送到后端存储；回放结果没有生成高亮指令

### 改动清单

#### 20.1 前端：录制步骤上报

**文件：`extension/content/observer.ts`**

在录制模式下，每记录一个步骤，通过 WS 发送到后端：

```typescript
// 在 click/input 事件处理中
if (recordingMode) {
  const step = {
    action: "click",
    selector: generateSelector(e.target),
    description: describeElement(e.target),
    timestamp: Date.now(),
  };
  recordedSteps.push(step);
  // 新增：实时上报到后端
  chrome.runtime.sendMessage({
    type: INTERNAL_MSG.FLOW_STEP,
    step,
  });
}
```

#### 20.2 Service Worker：步骤转发

**文件：`extension/background/ws-manager.ts`**

新增 `FLOW_STEP` 消息处理，转发到 WS：

```typescript
case INTERNAL_MSG.FLOW_STEP:
  ws.send(JSON.stringify({
    type: "flow_step",
    step: msg.step,
  }));
  break;
```

#### 20.3 后端：接收步骤 + 回放生成高亮

**文件：`backend/app.py`**

WS 消息路由新增 `flow_step` 类型：

```python
elif msg_type == "flow_step":
    # 转发到 learn_flow_tool.add_step()
    learn_flow_tool.add_step(
        action=msg["step"]["action"],
        selector=msg["step"]["selector"],
        description=msg["step"]["description"],
    )
```

**文件：`backend/agent.py`**

回放时生成高亮指令：

```python
# 在 guide_request 子图中
# 如果用户说"帮我回忆怎么创建项目"
# → 调用 learn_flow("replay", "创建项目")
# → 将回放的 steps 转为 highlight 指令下发
```

#### 20.4 前端：录制控制 UI

**文件：`extension/sidebar/panel.ts`**

新增录制按钮（长按录音按钮切换到录制模式）：

```typescript
// 录制模式切换
recordBtn.addEventListener("click", () => {
  if (recordingMode) {
    stopRecording();
  } else {
    startRecording();
  }
});
```

### 改动文件
```
extension/content/observer.ts    — 步骤实时上报
extension/background/ws-manager.ts — FLOW_STEP 消息转发
extension/sidebar/panel.ts       — 录制控制 UI
backend/app.py                   — flow_step WS 消息路由
backend/tools/learn_flow.py      — 回放生成高亮指令
```

### 验收标准
- 点击"录制"按钮 → 进入录制模式
- 在页面上点击 3 个元素 → 后端收到 3 个步骤
- 点击"停止" → 操作流保存到 Chroma
- 说"帮我回忆怎么 XX" → 回放为分步高亮指引

---

## T21: 视觉定位集成完善（P1）

### 目标
moondream2 视觉模型加载 + 截图→定位→高亮端到端跑通。

### 当前状态
- **后端** `visual_locate.py` — 工具已实现，等待 vision_model 注入
- **后端** `screenshot_annotate.py` — Pillow 标注已实现
- **缺失** `backend/vision/moondream.py` — 模型加载封装未实现
- **缺失** 前端截图 → 后端定位 → 前端高亮的完整链路

### 改动清单

#### 21.1 moondream2 模型封装

**新建文件：`backend/vision/moondream.py`**

```python
"""
求问 — Moondream2 视觉模型封装
==============================

moondream2 是一个 1.6B 参数的轻量视觉模型，
适合本地运行的元素定位任务。

模型来源：HuggingFace (vikhyatk/moondream2)
推理引擎：transformers + PyTorch
"""

class MoondreamVision:
    def __init__(self):
        self._model = None

    async def initialize(self) -> None:
        """加载 moondream2 模型。"""
        try:
            from transformers import AutoModelForCausalLM
            self._model = AutoModelForCausalLM.from_pretrained(
                "vikhyatk/moondream2",
                trust_remote_code=True,
                device_map="auto",
            )
        except Exception as e:
            logger.warning("moondream2 加载失败", error=str(e))

    async def locate_element(self, image_base64: str, description: str) -> dict:
        """
        在截图中定位元素。

        Returns:
            {"x": 100, "y": 200, "w": 80, "h": 30, "confidence": 0.85}
        """
        ...
```

#### 21.2 Agent 注入视觉模型

**文件：`backend/agent.py`**

```python
async def initialize(self) -> None:
    ...
    # 视觉模型（可选，不阻塞启动）
    try:
        from vision.moondream import MoondreamVision
        self._vision_model = MoondreamVision()
        await self._vision_model.initialize()
    except Exception:
        self._vision_model = None

    langchain_tools = get_langchain_tools(
        ...,
        vision_model=self._vision_model,
    )
```

#### 21.3 前端截图请求

**文件：`extension/content/screenshot.ts`**

已有截图逻辑，需要确保截图数据能发送到后端进行视觉定位。

### 改动文件
```
backend/vision/moondream.py     — 新建，模型封装
backend/agent.py                — 注入视觉模型
backend/Dockerfile              — 添加 transformers + torch 依赖（可选）
```

### 验收标准
- moondream2 模型可加载（或降级提示）
- `visual_locate(image, "创建按钮")` 返回坐标
- 坐标对应到正确的页面元素

---

## T22: MCP Server 集成（P2）

### 目标
让求问成为 MCP (Model Context Protocol) 工具服务器，供其他 AI Agent 调用。

### 价值
- 其他 Agent（如 Claude、Cursor）可以直接调用求问的文档检索、操作引导能力
- 生态价值：求问成为 AI 工具链的一部分

### MCP 协议概述
MCP 是 Anthropic 提出的标准协议，让 AI 模型与外部工具交互：
- **Server**：提供工具（tools）和资源（resources）
- **Client**：AI 模型通过 JSON-RPC 调用 Server 的工具

### 暴露的工具

| MCP Tool | 对应求问工具 | 说明 |
|----------|-------------|------|
| `search_docs` | SearchDocsTool | 从本地文档索引搜索 |
| `fetch_page` | FetchDocPageTool | 抓取页面正文 |
| `guide_element` | HighlightElementTool | 在页面上引导操作 |
| `classify_page` | ClassifyPageTool | 判断页面类型 |

### 改动清单

#### 22.1 新建 MCP Server

**新建文件：`backend/mcp/server.py`**

```python
"""
求问 — MCP Server
=================

让求问成为 MCP 工具服务器，供其他 AI Agent 调用。

协议：MCP (Model Context Protocol) by Anthropic
传输：stdio（标准输入输出）或 SSE（Server-Sent Events）

用法：
  # stdio 模式（供 Claude Desktop 等使用）
  python -m mcp.server

  # SSE 模式（供远程 Agent 使用）
  python -m mcp.server --transport sse --port 8701
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("qiuwen")

@server.tool()
async def search_docs(query: str, top_k: int = 5) -> str:
    """从本地文档索引中搜索相关信息。"""
    ...

@server.tool()
async def fetch_page(url: str) -> str:
    """获取指定 URL 的页面正文内容。"""
    ...

@server.tool()
async def guide_element(selector: str, description: str, page_url: str) -> str:
    """在页面上高亮指定元素，引导用户操作。"""
    ...

@server.tool()
async def classify_page(url: str) -> str:
    """判断页面类型（表单/列表/详情/仪表盘等）。"""
    ...
```

#### 22.2 更新依赖

**文件：`backend/requirements.txt`**

```diff
+# --- MCP Server ---
+mcp>=1.0.0
```

#### 22.3 入口脚本

**新建文件：`backend/mcp/__main__.py`**

```python
"""python -m mcp 启动入口。"""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server

async def main():
    server = Server("qiuwen")
    # 注册工具...
    async with stdio_server() as (read, write):
        await server.run(read, write)

asyncio.run(main())
```

### 改动文件
```
backend/mcp/server.py        — 新建，MCP Server 主体
backend/mcp/__main__.py      — 新建，启动入口
backend/requirements.txt     — 添加 mcp 依赖
```

### 验收标准
- `python -m mcp` 可启动 Server
- Claude Desktop 配置后可调用 search_docs 工具
- 返回结果格式符合 MCP 协议

---

## T23: 离线模式完善（P3）

### 目标
无网络时完整可用，所有功能有离线降级。

### 当前离线能力
| 功能 | 离线状态 | 说明 |
|------|----------|------|
| LLM 推理 | ✅ | Ollama 本地运行 |
| 文档检索 | ✅ | Chroma 本地运行 |
| 页面抓取 | ✅ | Scrapling httpx 降级 |
| TTS 语音 | ❌ | edge-tts 需要联网 |
| 浏览器指纹 | ✅ | 内置 UA 池降级 |

### 改动清单

#### 23.1 TTS 离线降级

**文件：`backend/voice/tts.py`**

添加离线 TTS 降级（pyttsx3 或简单蜂鸣音）：

```python
async def initialize(self) -> None:
    try:
        import edge_tts
        self._use_edge_tts = True
    except ImportError:
        # 降级到 pyttsx3（离线）
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._use_edge_tts = False
        except Exception:
            self._use_edge_tts = False
            logger.warning("TTS 不可用（edge-tts 和 pyttsx3 均未安装）")
```

#### 23.2 离线状态检测

**文件：`backend/app.py`**

新增 `/api/status` 端点，返回各模块在线/离线状态：

```python
@app.get("/api/status")
async def system_status():
    return {
        "ollama": await check_ollama(),
        "chroma": agent._long_term.is_healthy if agent else False,
        "tts": tts_service._use_edge_tts,
        "asr": asr_service._model is not None,
        "vision": agent._vision_model is not None if agent else False,
    }
```

#### 23.3 前端离线提示

**文件：`extension/sidebar/panel.ts`**

启动时检测后端状态，显示离线提示：

```typescript
// 启动时检查
fetch("/api/status").then(r => r.json()).then(status => {
  if (!status.tts) showHint("语音合成功能需要网络");
  if (!status.asr) showHint("语音识别功能需要安装模型");
});
```

### 改动文件
```
backend/voice/tts.py        — pyttsx3 离线降级
backend/app.py              — /api/status 端点
extension/sidebar/panel.ts  — 离线提示
```

### 验收标准
- 断网后 LLM + 检索 + 高亮正常工作
- TTS 降级到 pyttsx3 或提示不可用
- `/api/status` 返回各模块状态

---

## 执行顺序

```
T19 (知识库扩充) ──────────────────────────────┐
                                                │
T20 (操作流端到端) ─────────────────────────────┤
                                                ├─→ 集成测试
T21 (视觉定位) ────────────────────────────────┤
                                                │
T22 (MCP Server) ──────────────────────────────┤
                                                │
T23 (离线模式) ────────────────────────────────┘
```

建议执行顺序：
1. **T19** — 知识库扩充（独立，纯数据，无代码改动）
2. **T20** — 操作流端到端（前后端联动，核心体验）
3. **T21** — 视觉定位（后端为主，模型依赖）
4. **T22** — MCP Server（独立模块，生态价值）
5. **T23** — 离线模式（收尾性质）

---

## 验收标准

| 指标 | 目标 |
|------|------|
| 知识库条目 | >= 200 条 |
| 操作流全链路 | 录制→回放→高亮 跑通 |
| 视觉定位 | moondream2 加载 + 坐标返回 |
| MCP Server | Claude Desktop 可调用 |
| 离线可用性 | 断网后核心功能正常 |
| 测试通过率 | 100% (现有 119 + 新增) |
