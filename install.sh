#!/bin/bash
# ============================================================
#  求问 - 本地智能网页引导球 安装脚本 (Mac/Linux)
# ============================================================
set -e

echo "========================================"
echo "  求问 - 本地智能网页引导球 安装程序"
echo "========================================"
echo

# Step 1: 检测 Docker
echo "[1/6] 检测 Docker..."
if ! command -v docker &> /dev/null; then
    echo "❌ 未检测到 Docker"
    echo "请先安装 Docker: https://www.docker.com/products/docker-desktop/"
    exit 1
fi
echo "✅ Docker 已安装"

# Step 2: 检测 Ollama
echo "[2/6] 检测 Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "⚠️ 未检测到 Ollama，正在安装..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        curl -L https://ollama.com/download/Ollama-darwin.zip -o Ollama.zip
        unzip Ollama.zip -d /Applications/
        rm Ollama.zip
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
fi
echo "✅ Ollama 已安装"

# Step 3: 启动 Ollama 服务
echo "[3/6] 启动 Ollama 服务..."
ollama serve &
sleep 3

# Step 4: 拉取模型
echo "[4/6] 拉取 AI 模型（约 4GB，首次需要下载）..."
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
echo "✅ 模型就绪"

# Step 5: 启动服务
echo "[5/6] 启动求问服务..."
docker compose up -d
echo "✅ 服务已启动"

# Step 6: 提示安装扩展
echo "[6/6] 安装浏览器扩展..."
echo
echo "========================================"
echo "  安装完成！请按以下步骤操作："
echo "========================================"
echo
echo "  1. 打开 Chrome 浏览器"
echo "  2. 地址栏输入: chrome://extensions"
echo "  3. 开启右上角「开发者模式」"
echo "  4. 点击「加载已解压的扩展程序」"
echo "  5. 选择本目录下的 extension 文件夹"
echo
echo "  然后打开任意网页，点击侧边栏的求问球即可使用！"
echo
