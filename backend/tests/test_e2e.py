"""
求问 — 端到端测试
=================

测试完整的用户流程：
  1. 健康检查
  2. 系统状态
  3. API 端点
  4. 错误处理
  5. 性能测试
"""

import pytest
import asyncio
import time
from httpx import AsyncClient, ASGITransport

# 跳过如果依赖不可用
pytest.importorskip("httpx")


@pytest.fixture
async def client():
    """创建测试客户端"""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# 基础端点测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(client):
    """测试健康检查端点"""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "model_strategy" in data


@pytest.mark.asyncio
async def test_system_status(client):
    """测试系统状态端点"""
    response = await client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert "ollama" in data
    assert "chroma" in data


@pytest.mark.asyncio
async def test_get_config(client):
    """测试获取配置端点"""
    response = await client.get("/api/config")
    assert response.status_code == 200

    data = response.json()
    assert "model_strategy" in data
    assert "ollama_model" in data


@pytest.mark.asyncio
async def test_index_status(client):
    """测试索引状态端点"""
    response = await client.get("/api/index/status")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_enterprise_status(client):
    """测试企业版状态端点"""
    response = await client.get("/api/enterprise/status")
    assert response.status_code == 200

    data = response.json()
    assert "current_source" in data


# ---------------------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_endpoint(client):
    """测试无效端点返回 404"""
    response = await client.get("/api/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_method_not_allowed(client):
    """测试方法不允许"""
    response = await client.delete("/health")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# 并发测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_health_checks(client):
    """测试并发健康检查"""

    async def check_health():
        response = await client.get("/health")
        return response.status_code

    # 并发发送 10 个请求
    tasks = [check_health() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # 所有请求都应该成功
    assert all(r == 200 for r in results)


# ---------------------------------------------------------------------------
# 性能测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_time_health(client):
    """测试健康检查响应时间"""
    start = time.time()
    response = await client.get("/health")
    duration = time.time() - start

    assert response.status_code == 200
    assert duration < 1.0  # 响应时间 < 1 秒


@pytest.mark.asyncio
async def test_response_time_config(client):
    """测试配置端点响应时间"""
    start = time.time()
    response = await client.get("/api/config")
    duration = time.time() - start

    assert response.status_code == 200
    assert duration < 1.0  # 响应时间 < 1 秒


@pytest.mark.asyncio
async def test_throughput(client):
    """测试吞吐量"""

    async def make_request():
        response = await client.get("/health")
        return response.status_code

    # 模拟 20 个并发请求
    start = time.time()
    tasks = [make_request() for _ in range(20)]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start

    # 所有请求都应该成功
    assert all(r == 200 for r in results)

    # 吞吐量 > 10 请求/秒
    throughput = len(results) / duration
    assert throughput > 10
