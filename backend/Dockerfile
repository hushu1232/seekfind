# ============================================================
#  求问 — 后端 Dockerfile
# ============================================================
#  多阶段构建：
#    base → 安装系统依赖 + Python 依赖
#    final → 复制应用代码 + 内置知识库 + 启动脚本
#
#  构建：docker build -t qiuwen-bff .
#  运行：docker run -p 8700:8700 qiuwen-bff
# ============================================================

FROM python:3.11-slim AS base

WORKDIR /app

# --- 系统依赖 ---
# curl: entrypoint.sh 中检测 Ollama 健康状态
# ca-certificates: HTTPS 请求需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Python 依赖（利用 Docker 层缓存） ---
# 先复制 requirements.txt，单独安装依赖层
# 这样只有 requirements.txt 变化时才会重新 pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 应用代码 ---
COPY . .

# --- 内置常识库 ---
COPY knowledge/ /app/knowledge/

# --- 数据目录（指纹存储等） ---
RUN mkdir -p /app/data

# --- 启动入口 ---
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8700

ENTRYPOINT ["/entrypoint.sh"]
