#!/bin/bash
# ============================================================
#  求问 — 后端启动入口脚本
# ============================================================
#  执行顺序：
#    1. 检测 Ollama 服务是否可达（最多等 30 秒）
#    2. 拉取默认模型（如果不存在）
#    3. 启动 FastAPI 服务（uvicorn）
#
#  环境变量（从 docker-compose.yml 传入）：
#    BFF_PORT           服务端口（默认 8700）
#    OLLAMA_BASE_URL    Ollama API 地址
#    OLLAMA_MODEL       默认模型名（默认 qwen2.5:7b）
#    LOG_LEVEL          日志级别（默认 info）
# ============================================================
set -e

echo "========================================"
echo "  求问 — 后端服务启动中..."
echo "========================================"

# --- Step 1: 检测 Ollama 服务 ---
# 从 OLLAMA_BASE_URL 提取主机地址（去掉 /v1 后缀）
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434/v1}"
OLLAMA_HOST="${OLLAMA_URL%/v1}"
echo "[1/3] 检测 Ollama 服务 (${OLLAMA_HOST})..."

for i in $(seq 1 30); do
    if curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
        echo "✅ Ollama 服务就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "⚠️  Ollama 服务未检测到（等待 30 秒超时）"
        echo "   请确保 Ollama 已启动：ollama serve"
        echo "   后端将继续启动，但 LLM 功能可能不可用"
    fi
    sleep 1
done

# --- Step 2: 拉取默认模型 ---
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
echo "[2/3] 确保模型 ${OLLAMA_MODEL} 可用..."
# 发送 pull 请求（如果模型已存在则秒回）
curl -s "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"${OLLAMA_MODEL}\"}" > /dev/null 2>&1 || true
echo "✅ 模型就绪"

# --- Step 3: 启动 FastAPI 服务 ---
echo "[3/3] 启动 FastAPI 服务 (端口 ${BFF_PORT:-8700})..."
exec uvicorn app:app \
    --host 0.0.0.0 \
    --port "${BFF_PORT:-8700}" \
    --log-level "${LOG_LEVEL:-info}" \
    --ws websockets
