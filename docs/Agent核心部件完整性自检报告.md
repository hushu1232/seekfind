# Agent 核心部件完整性自检报告

> 日期：2026-05-31 | 基于项目代码逐项验证

---

## 一、六大核心部件评估

### 1. 大语言模型（LLM）—— 大脑

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| 本地 LLM (Ollama + qwen2.5:7b) | ✅ | `agent.py:170-174` | ChatOpenAI 对接 Ollama /v1 端点 |
| Function Calling / Tool Use | ✅ | `agent.py:200` | `bind_tools(langchain_tools)` |
| 流式输出 | ✅ | `agent.py:174` | `streaming=True` |
| 模型降级策略 | ✅ | `agent.py:221-230` | hybrid 模式：连续失败 N 次切云端 |
| 上下文窗口管理 | 🟡 | `agent.py:330` | SystemPrompt + 最近对话 + 检索结果，无 token 计数 |

**质量评价：良**
- 降级策略完整（local → cloud）
- 缺少 token 计数和上下文截断逻辑

**改进建议：**
- 添加 token 计数（tiktoken），超过阈值自动截断旧消息
- 支持上下文压缩（长对话摘要）

---

### 2. 工具（Tools）—— 手脚

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| 5+ 工具 | ✅ | `tools/` | 12 个工具 |
| 统一 Schema | ✅ | 各工具 `schema` 属性 | Pydantic create_model 动态生成 |
| ToolNode 调度 | ✅ | `agent.py:40,117` | LangGraph ToolNode |
| 错误处理 | ✅ | 各工具 `execute()` | try-except + JSON error 返回 |
| 异步非阻塞 | ✅ | 各工具 `async def execute` | asyncio 原生 |

**质量评价：优**
- 12 个工具覆盖文档检索/页面抓取/高亮/视觉/语音/浏览器控制
- 依赖注入通过 functools.partial 预绑定
- 懒加载（importlib）减少启动开销

**改进建议：**
- 添加工具调用超时（已有常量，需在 ToolNode 层面强制执行）

---

### 3. 记忆（Memory）—— 长期与短期

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| 短期记忆 (State) | ✅ | `memory/short_term.py` | deque(maxlen=100) 对话上下文 |
| 长期记忆 (ChromaDB) | ✅ | `memory/long_term.py` | Chroma HttpClient + 重试 |
| 记忆读写工具 | ✅ | `tools/memory_tools.py` | save_memory + recall_memory |
| 隐私脱敏 | ✅ | `content/privacy.ts` | 邮箱/手机/密码/密钥脱敏 |
| 持久化记忆 | ✅ | `memory/persistent_memory.py` | SQLite 用户画像/案例/预测 |
| 指纹存储 | ✅ | `memory/fingerprint_storage.py` | SQLite 元素指纹 + 模糊匹配 |

**质量评价：优**
- 三层记忆架构：短期(deque) + 长期(Chroma) + 持久化(SQLite)
- EverOS 架构集成：Profile/Case/Foresight
- 隐私脱敏在采集层执行

**改进建议：**
- Chroma embedding 切换为 Ollama nomic-embed-text（当前用默认英文模型）

---

### 4. 规划与工作流（Planner & Workflow）—— 决策中枢

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| LangGraph StateGraph | ✅ | `agent.py:115-117` | StateGraph + add_node + add_edge |
| 意图分类节点 | ✅ | `agent.py:249-253` | classify_intent (doc/guide/chat) |
| 条件路由 | ✅ | `agent.py:109-114` | should_continue 条件边 |
| 子图路由 | ✅ | `agent.py:296-304` | doc→RAG / guide→引导 / chat→闲聊 |
| 循环重试 | ✅ | `agent.py:109-114` | agent → tools → agent 循环 |
| 可观测性 | 🟡 | `agent.py:332-365` | yield tool_call/tool_result，无 tracing |

**质量评价：良**
- 三子图架构清晰（RAG / 引导 / 闲聊）
- 意图分类 + 条件路由完整
- 缺少 LangSmith/OpenTelemetry tracing

**改进建议：**
- 集成 structlog tracing（已有 structlog，需添加 span 追踪）
- 添加工具调用失败后的重试规划

---

### 5. 知识库与检索（Knowledge & Retrieval）

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| 向量数据库 (ChromaDB) | ✅ | `memory/long_term.py` | HttpClient + cosine 相似度 |
| 混合检索 | ✅ | `tools/search_docs.py` | 向量 + BM25 + RRF 融合 |
| 三集合 | ✅ | `memory/long_term.py:66-70` | docs / elements / flows |
| RRF 融合排序 | ✅ | `tools/search_docs.py:224-249` | Reciprocal Rank Fusion |
| 增量更新 | ✅ | `indexer/build_index.py` | md5 去重 + 增量写入 |
| 文档索引 | ✅ | `indexer/crawler.py` | ScraplingFetcher + 智能分块 |
| 知识库 | ✅ | `knowledge/builtin/` | 33 产品 204 条，100% 选择器 |

**质量评价：优**
- 混合检索架构完整（向量 + BM25 + RRF）
- 增量索引 + 智能分块
- 204 条内置知识，100% 选择器覆盖

**改进建义：**
- 添加 Reranker 模型（如 bge-reranker）提升排序质量

---

### 6. 感知与执行环境（Perception & Execution）

| 检查点 | 状态 | 代码位置 | 说明 |
|--------|:---:|----------|------|
| DOM 结构获取 | ✅ | `content/snapshot.ts` | 无障碍树快照 + @eN 引用 |
| 截图 | ✅ | `content/screenshot.ts` | captureVisibleTab |
| 用户事件采集 | ✅ | `content/observer.ts` | click/input/scroll/route |
| 高亮元素 | ✅ | `content/highlight.ts` | pulse/glow/arrow + 粒子 |
| 三级视觉定位 | ✅ | `tools/` | selector → moondream2 → 截图标注 |
| WS 通信 | ✅ | `background/ws-manager.ts` | WebSocket + 断线重连 |
| 困惑检测 | ✅ | `content/observer.ts:47-49` | 连续点击 3 次触发 |
| 无障碍树快照 | ✅ | `content/snapshot.ts` | @eN 引用 + 语义定位 |
| 悬浮球 | ✅ | `content/float-ball.ts` | Shadow DOM + 拖拽 + 四状态 |

**质量评价：优**
- 感知层完整（DOM + 截图 + 事件 + 无障碍树）
- 执行层完整（高亮 + 交互 + 悬浮球）
- 三级定位降级链完整

**改进建议：**
- 添加页面变化检测（MutationObserver 触发重新快照）

---

## 二、延伸部件评估

| 部件 | 状态 | 说明 |
|------|:---:|------|
| 多智能体协作 | ❌ | 单 Agent 架构，无多 Agent 分工 |
| 可观测性 | 🟡 | structlog 日志有，无 tracing/span |
| 人机回环 (HITL) | ✅ | 高亮反馈按钮（指对了/指错了） |
| 自我反思 | ❌ | Agent 不评估自身输出质量 |

---

## 三、总体评分

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  1. LLM (大脑)           ████████░░  8/10               │
│  2. 工具 (手脚)          █████████░  9/10               │
│  3. 记忆 (长期+短期)     █████████░  9/10               │
│  4. 规划 (决策中枢)      ████████░░  8/10               │
│  5. 知识库 (检索)        █████████░  9/10               │
│  6. 感知执行 (交互)      █████████░  9/10               │
│                                                         │
│  延伸部件                 ████░░░░░░  4/10               │
│                                                         │
│  总体评分:  8.5 / 10                                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 四、优先改进的三项建议

### 1. 上下文窗口管理（P0）

**问题**：长对话时上下文可能超出模型限制，导致截断或报错。

**方案**：
```python
# agent.py 中添加 token 计数
import tiktoken

def _trim_messages(self, messages, max_tokens=4096):
    enc = tiktoken.encoding_for_model("gpt-4")
    total = sum(len(enc.encode(m.content)) for m in messages)
    while total > max_tokens and len(messages) > 2:
        removed = messages.pop(1)  # 保留 system + 最新 user
        total -= len(enc.encode(removed.content))
    return messages
```

### 2. Reranker 提升检索质量（P1）

**问题**：RRF 融合后无精细排序，top_k 结果可能不准。

**方案**：
```python
# 添加 bge-reranker 或 Cohere rerank
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self):
        self.model = CrossEncoder("BAAI/bge-reranker-base")

    def rerank(self, query: str, docs: list[str], top_k: int = 5):
        pairs = [(query, doc) for doc in docs]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
```

### 3. 可观测性 — LangSmith Tracing（P2）

**问题**：Agent 执行过程不可追踪，调试困难。

**方案**：
```python
# 集成 LangSmith
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "xxx"

# 或使用 structlog span
from structlog import get_logger
logger = get_logger()

async def _run_graph(self, ...):
    with logger.span("agent.run_graph") as span:
        span.set_attribute("intent", intent)
        async for event in graph.astream(...):
            ...
```

---

## 五、检查清单总览

| # | 检查点 | 状态 |
|---|--------|:---:|
| 1 | 本地 LLM (Ollama) | ✅ |
| 2 | Function Calling | ✅ |
| 3 | 流式输出 | ✅ |
| 4 | 模型降级 | ✅ |
| 5 | 上下文窗口管理 | 🟡 |
| 6 | 5+ 工具 | ✅ (12) |
| 7 | 统一 Schema | ✅ |
| 8 | ToolNode 调度 | ✅ |
| 9 | 错误处理 | ✅ |
| 10 | 异步非阻塞 | ✅ |
| 11 | 短期记忆 | ✅ |
| 12 | 长期记忆 | ✅ |
| 13 | 记忆读写工具 | ✅ |
| 14 | 隐私脱敏 | ✅ |
| 15 | LangGraph StateGraph | ✅ |
| 16 | 意图分类 + 路由 | ✅ |
| 17 | 条件边 | ✅ |
| 18 | 循环重试 | ✅ |
| 19 | 可观测性 | 🟡 |
| 20 | ChromaDB | ✅ |
| 21 | 混合检索 | ✅ |
| 22 | 三集合 | ✅ |
| 23 | RRF 融合 | ✅ |
| 24 | 增量更新 | ✅ |
| 25 | DOM 获取 | ✅ |
| 26 | 截图 | ✅ |
| 27 | 事件采集 | ✅ |
| 28 | 高亮执行 | ✅ |
| 29 | 三级定位 | ✅ |
| 30 | WS 通信 | ✅ |
| 31 | 困惑检测 | ✅ |

**通过率：29/31 (93.5%)**
