"""
求问 — 测试配置 (conftest.py)
=============================

提供 pytest fixtures：
  - short_term_memory: ShortTermMemory 实例
  - mock_long_term_memory: Mock 的 LongTermMemory（不连接 Chroma）
  - sample_crawled_doc: 示例爬取文档
  - sample_settings: 测试配置
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# 确保 backend 目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def short_term_memory():
    """创建 ShortTermMemory 实例。"""
    from memory.short_term import ShortTermMemory
    return ShortTermMemory(max_turns=50)


@pytest.fixture
def mock_long_term_memory():
    """
    Mock 的 LongTermMemory（不连接真实 Chroma）。
    所有方法都返回预设的 mock 数据。
    """
    mem = AsyncMock()
    mem.search = AsyncMock(return_value=[
        {"text": "测试文档内容1", "metadata": {"source_url": "http://test.com"}},
        {"text": "测试文档内容2", "metadata": {"source_url": "http://test.com"}},
    ])
    mem.add = AsyncMock()
    mem.save_memory = AsyncMock()
    mem.recall_memory = AsyncMock(return_value=[
        {"text": "测试记忆内容", "metadata": {}},
    ])
    mem.get_collection_count = AsyncMock(return_value=10)
    mem.close = AsyncMock()
    return mem


@pytest.fixture
def sample_crawled_doc():
    """示例爬取文档。"""
    from indexer.crawler import CrawledDoc
    return CrawledDoc(
        url="https://docs.example.com/guide",
        title="使用指南",
        text="这是一篇测试文档。\n\n第一章：入门\n\n1. 安装\n2. 配置\n3. 启动\n\n第二章：使用\n\n1. 创建项目\n2. 导入数据\n3. 运行分析",
        depth=0,
    )


@pytest.fixture
def sample_builtin_json():
    """示例内置常识库 JSON。"""
    return {
        "product": "TestProduct",
        "version": "2026",
        "entries": [
            {
                "question": "怎么创建项目？",
                "answer": "1. 点击新建\n2. 输入名称\n3. 点击确定",
                "selectors": ["#create-btn"],
                "url_pattern": "test.example.com/*",
            },
            {
                "question": "怎么删除项目？",
                "answer": "1. 选择项目\n2. 点击删除\n3. 确认删除",
                "selectors": ["#delete-btn"],
                "url_pattern": "test.example.com/*",
            },
        ],
    }


@pytest.fixture
def tmp_knowledge_dir(tmp_path, sample_builtin_json):
    """创建临时常识库目录。"""
    knowledge_dir = tmp_path / "knowledge" / "builtin"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "test_product.json").write_text(
        json.dumps(sample_builtin_json, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(knowledge_dir)


@pytest.fixture
def fingerprint_storage(tmp_path):
    """创建临时指纹存储（不污染生产数据库）。"""
    from memory.fingerprint_storage import FingerprintStorage
    db_path = str(tmp_path / "test_fingerprints.db")
    return FingerprintStorage(db_path)
