# 🔮 求问 — 本地智能网页引导球

> 一个完全本地化的 AI 网页引导助手。问它"在哪里创建项目"，它会直接在页面上高亮给你看。

## ✨ 特性

- 🏠 **完全本地化** — 默认使用 Ollama 本地推理，数据不出本机
- 🔍 **智能检索** — 混合向量检索 + BM25 关键词检索，精准定位文档
- 🎯 **视觉引导** — 直接在页面上高亮操作元素，不用猜
- 🧠 **三层模型策略** — 本地 7B → 本地 14B → 云端 API，自动降级
- 🔒 **隐私优先** — 密码字段、邮箱、手机号自动脱敏
- 🎤 **语音交互** — 说"小求小求"唤醒，语音提问（Phase 4）

## 📦 快速开始

### 方式一：一键安装（推荐）

**Windows：**
```bash
# 双击 install.bat
```

**Mac/Linux：**
```bash
bash install.sh
```

### 方式二：手动安装

#### 1. 安装前置依赖

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Ollama](https://ollama.com/)

#### 2. 拉取 AI 模型

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

#### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 按需修改配置
```

#### 4. 启动后端服务

```bash
docker compose up -d
```

验证服务状态：
```bash
curl http://localhost:8700/health
# 应返回: {"status":"ok","model_strategy":"hybrid"}
```

#### 5. 安装浏览器扩展

1. 打开 Chrome，地址栏输入 `chrome://extensions`
2. 开启右上角「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择本项目的 `extension/` 文件夹

#### 6. 开始使用

打开任意网页，点击侧边栏的求问球，输入你的问题！

## 🏗️ 项目结构

```
求问/
├── backend/                    # 后端服务 (FastAPI + LangGraph)
│   ├── app.py                  # FastAPI 主入口
│   ├── config.py               # 配置管理 (pydantic-settings)
│   ├── agent.py                # LangGraph Agent 引擎
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── memory/                 # 记忆模块
│   │   ├── short_term.py       # 对话上下文 (最多 50 轮)
│   │   └── long_term.py        # Chroma 向量库封装
│   ├── indexer/                 # 文档索引引擎
│   │   ├── crawler.py          # 文档爬虫 (httpx + trafilatura)
│   │   ├── build_index.py      # 索引构建器 (分块 + embedding)
│   │   └── cli.py              # 命令行工具
│   ├── tools/                  # Agent 工具集
│   │   ├── search_docs.py      # 混合检索 (Chroma + BM25 + RRF)
│   │   ├── fetch_doc_page.py   # 页面抓取
│   │   └── memory_tools.py     # 长期记忆读写
│   ├── vision/                 # 视觉定位 (Phase 2)
│   │   └── moondream.py        # moondream2 视觉模型
│   ├── voice/                  # 语音交互 (Phase 4)
│   │   ├── asr.py              # 语音识别 (Vosk)
│   │   └── tts.py              # 语音合成 (edge-tts)
│   └── knowledge/builtin/      # 内置常识库 (50+ 产品)
│       ├── github.json
│       ├── vscode.json
│       └── docker.json
│
├── extension/                  # 浏览器扩展 (Manifest V3 + TypeScript)
│   ├── manifest.json
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── background/
│   │   └── service_worker.ts   # WS 连接 + 消息路由
│   ├── sidebar/
│   │   ├── index.html          # 侧边栏面板
│   │   ├── panel.ts            # 对话逻辑
│   │   ├── ball.ts             # 3D 球体 (Three.js, Phase 3)
│   │   └── settings.ts         # 设置面板
│   ├── content/
│   │   ├── observer.ts         # DOM 观察者
│   │   ├── highlight.ts        # 高亮渲染引擎
│   │   └── privacy.ts          # 隐私脱敏
│   └── common/
│       ├── types.ts            # 类型定义
│       ├── constants.ts        # 常量
│       └── browser-compat.ts   # 浏览器兼容层
│
├── docker-compose.yml          # Docker 编排
├── .env.example                # 环境变量模板
├── install.bat                 # Windows 一键安装
├── install.sh                  # Mac/Linux 一键安装
└── README.md                   # 本文件
```

## 🔧 配置说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_STRATEGY` | `hybrid` | 模型策略：local / cloud / hybrid |
| `OLLAMA_MODEL` | `qwen2.5:7b` | 本地模型 |
| `CLOUD_MODEL` | `gpt-4o-mini` | 云端模型 |
| `FALLBACK_THRESHOLD` | `3` | 连续失败 N 次后自动降级 |
| `PRIVACY_SANITIZE_ENABLED` | `true` | 自动脱敏 |

## 📋 开发路线

- [x] **Phase 1** (第 1-2 周)：核心闭环 — 提问 → 检索 → 文本回答
- [ ] **Phase 2** (第 3-4 周)：视觉引导 — 高亮元素、截图标注
- [ ] **Phase 3** (第 5-6 周)：交互体验 — 3D 球体、骨架预埋、主动监控
- [ ] **Phase 4** (第 7-8 周)：语音封装 — ASR/TTS、一键部署

## 📄 技术文档

详细技术栈锁定、任务拆解、劣势攻克方案见：[求问-技术栈与任务拆解.md](求问/docs/求问-技术栈与任务拆解.md)

## 📜 许可证

MIT
