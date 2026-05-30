# ============================================================
#  求问 — 后端 Dockerfile
#  基于 Python 3.11-slim，安装依赖，启动 FastAPI 服务
# ============================================================
FROM python:3.11-slim AS base

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 内置常识库
COPY knowledge/ /app/knowledge/

# 入口脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8700

ENTRYPOINT ["/entrypoint.sh"]
