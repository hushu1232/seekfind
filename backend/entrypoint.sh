#!/bin/bash
# ============================================================
#  求问 — 后端启动入口
#  1. 检测 Ollama 是否可用
#  2. 拉取默认模型（如果不存在）
#  3. 启动 FastAPI 服务
# ============================================================
set -e

echo "========================================"
echo "  求问 — 后端服务启动中..."
echo "========================================"

# 检测 Ollama
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434/v1}"
OLLAMA_HOST="${OLLAMA_URL%/v1}"
echo "[1/3] 检测 Ollama 服务 (${OLLAMA_HOST})..."

for i in $(seq 1 30); do
    if curl -s "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
        echo "✅ Ollama 服务就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "⚠️ Ollama 服务未检测到，请确保 Ollama 已启动"
        echo "   运行: ollama serve"
    fi
    sleep 1
done

# 拉取默认模型
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
echo "[2/3] 确保模型 ${OLLAMA_MODEL} 可用..."
curl -s "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"${OLLAMA_MODEL}\"}" || true

echo "[3/3] 启动 FastAPI 服务..."
exec uvicorn app:app \
    --host 0.0.0.0 \
    --port "${BFF_PORT:-8700}" \
    --log-level "${LOG_LEVEL:-info}" \
    --ws websockets
