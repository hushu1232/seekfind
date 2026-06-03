@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   求问 — 企业版安装脚本
echo   版本: 2.0 (Enterprise)
echo   面向: 企业员工培训
echo ============================================================
echo.

REM 颜色定义
set "GREEN=[92m"
set "RED=[91m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "RESET=[0m"

REM 1. 检测系统
echo %BLUE%[1/8] 检测系统环境...%RESET%

REM 检测 Windows 版本
for /f "tokens=4-5 delims=. " %%i in ('ver') do set VERSION=%%i.%%j
echo Windows 版本: %VERSION%

REM 检测管理员权限
net session >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%提示: 建议以管理员身份运行以获得最佳体验%RESET%
)

REM 2. 检测 Docker
echo.
echo %BLUE%[2/8] 检测 Docker...%RESET%
docker --version >nul 2>&1
if errorlevel 1 (
    echo %RED%❌ Docker 未安装%RESET%
    echo.
    echo 正在打开 Docker 下载页面...
    echo 请安装 Docker Desktop 后重新运行此脚本
    start https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)
for /f "tokens=3" %%i in ('docker --version') do set DOCKER_VER=%%i
echo %GREEN%✅ Docker %DOCKER_VER% 已安装%RESET%

REM 3. 检测 Ollama
echo.
echo %BLUE%[3/8] 检测 Ollama...%RESET%
ollama --version >nul 2>&1
if errorlevel 1 (
    echo %RED%❌ Ollama 未安装%RESET%
    echo.
    echo 正在打开 Ollama 下载页面...
    echo 请安装 Ollama 后重新运行此脚本
    start https://ollama.com/download
    pause
    exit /b 1
)
echo %GREEN%✅ Ollama 已安装%RESET%

REM 4. 配置企业版
echo.
echo %BLUE%[4/8] 配置企业版...%RESET%

REM 复制环境变量
if not exist .env (
    copy .env.example .env
    echo %GREEN%✅ 环境变量已创建%RESET%
)

REM 询问是否配置企业 API
echo.
echo 是否配置企业 API？（本地不可用时的备选方案）
echo   - 输入 Y 配置企业 API
echo   - 输入 N 跳过（仅使用本地模型）
set /p CONFIGURE_ENTERPRISE="请选择 (Y/N): "

if /i "%CONFIGURE_ENTERPRISE%"=="Y" (
    echo.
    echo 请输入企业 API 配置：
    set /p ENTERPRISE_URL="API 地址 (如 https://api.company.com/v1): "
    set /p ENTERPRISE_KEY="API Key: "
    set /p ENTERPRISE_MODEL="模型名称 (如 gpt-4o，留空使用默认): "

    REM 写入 .env 文件
    echo. >> .env
    echo # 企业版配置 >> .env
    echo ENTERPRISE_API_BASE_URL=!ENTERPRISE_URL! >> .env
    echo ENTERPRISE_API_KEY=!ENTERPRISE_KEY! >> .env
    if not "!ENTERPRISE_MODEL!"=="" (
        echo ENTERPRISE_MODEL=!ENTERPRISE_MODEL! >> .env
    )
    echo ENTERPRISE_AUTO_FALLBACK=true >> .env
    echo ENTERPRISE_NOTIFY_USER=true >> .env
    echo ENTERPRISE_PRIVACY_WARNING=true >> .env

    echo %GREEN%✅ 企业 API 已配置%RESET%
) else (
    echo %YELLOW%跳过企业 API 配置%RESET%
)

REM 5. 启动服务
echo.
echo %BLUE%[5/8] 启动服务...%RESET%

REM 启动 Ollama
echo 启动 Ollama 服务...
start /b ollama serve
timeout /t 3 >nul

REM 检测 Ollama 是否启动
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%⚠️ Ollama 启动中，请稍候...%RESET%
    timeout /t 5 >nul
)
echo %GREEN%✅ Ollama 服务已启动%RESET%

REM 6. 下载模型
echo.
echo %BLUE%[6/8] 下载 AI 模型...%RESET%
echo 这可能需要几分钟，取决于您的网络速度
echo.

ollama pull qwen2.5:7b
if errorlevel 1 (
    echo %RED%❌ 模型下载失败%RESET%
    echo 请检查网络连接后重试
    pause
    exit /b 1
)
echo %GREEN%✅ 模型下载完成%RESET%

REM 7. 启动后端
echo.
echo %BLUE%[7/8] 启动后端服务...%RESET%

REM 启动 Docker Compose
docker compose up -d
if errorlevel 1 (
    echo %RED%❌ 后端启动失败%RESET%
    echo 请查看错误信息并修复
    pause
    exit /b 1
)

REM 等待后端启动
echo 等待后端启动...
timeout /t 5 >nul

REM 验证后端
curl -s http://localhost:8700/health >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%⚠️ 后端启动中，请稍候...%RESET%
    timeout /t 5 >nul
)

REM 8. 验证安装
echo.
echo %BLUE%[8/8] 验证安装...%RESET%

REM 检查后端健康状态
curl -s http://localhost:8700/health >nul 2>&1
if errorlevel 1 (
    echo %RED%❌ 后端未启动%RESET%
) else (
    echo %GREEN%✅ 后端服务正常%RESET%
)

REM 检查 Ollama 状态
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo %RED%❌ Ollama 未启动%RESET%
) else (
    echo %GREEN%✅ Ollama 服务正常%RESET%
)

REM 检查企业 API（如果配置了）
if /i "%CONFIGURE_ENTERPRISE%"=="Y" (
    curl -s http://localhost:8700/api/enterprise/check >nul 2>&1
    if errorlevel 1 (
        echo %YELLOW%⚠️ 企业 API 连接失败（不影响本地使用）%RESET%
    ) else (
        echo %GREEN%✅ 企业 API 连接正常%RESET%
    )
)

REM 完成
echo.
echo %GREEN%============================================================%RESET%
echo %GREEN%  企业版安装完成！%RESET%
echo %GREEN%============================================================%RESET%
echo.
echo 请在浏览器中加载扩展:
echo.
echo   Edge:
echo     1. 打开 edge://extensions
echo     2. 开启"开发者模式"
echo     3. 点击"加载已解压的扩展程序"
echo     4. 选择 extension\dist 文件夹
echo.
echo   Chrome:
echo     1. 打开 chrome://extensions
echo     2. 开启"开发者模式"
echo     3. 点击"加载已解压的扩展程序"
echo     4. 选择 extension\dist 文件夹
echo.
echo 服务地址:
echo   - 后端: http://localhost:8700
echo   - 健康检查: http://localhost:8700/health
echo   - 企业状态: http://localhost:8700/api/enterprise/status
echo.
echo 企业部署说明:
echo   - 本地模型优先，企业 API 作为备选
echo   - 本地不可用时自动降级到企业 API
echo   - 降级时会显示隐私警告
echo.
echo 按任意键退出...
pause >nul
