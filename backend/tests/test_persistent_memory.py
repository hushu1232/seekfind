"""
求问 — 持久化记忆系统测试
========================

测试：
  - PersistentMemory CRUD
  - UserProfile 增删改查
  - AgentCase 保存/查找/失败记录
  - ProfileExtractor 用户画像提取
  - CaseExtractor 案例提取
  - ForesightExtractor 前瞻预测
"""

import time
import pytest

from memory.types import MemoryType, MemoryRecord, UserProfile, AgentCase
from memory.persistent_memory import PersistentMemory
from memory.extractors import ProfileExtractor, CaseExtractor, ForesightExtractor


class TestPersistentMemory:
    """PersistentMemory CRUD 测试。"""

    @pytest.fixture
    def memory(self, tmp_path):
        return PersistentMemory(str(tmp_path / "test.db"))

    def test_save_and_get(self, memory):
        record = MemoryRecord(
            id="test_1",
            type=MemoryType.EPISODE,
            content="用户问了 GitHub PR 问题",
        )
        memory.save_memory(record)
        result = memory.get_memory("test_1")
        assert result is not None
        assert result.content == "用户问了 GitHub PR 问题"
        assert result.type == MemoryType.EPISODE

    def test_search_by_type(self, memory):
        memory.save_memory(MemoryRecord(id="e1", type=MemoryType.EPISODE, content="ep1"))
        memory.save_memory(MemoryRecord(id="f1", type=MemoryType.ATOMIC_FACT, content="fact1"))
        memory.save_memory(MemoryRecord(id="e2", type=MemoryType.EPISODE, content="ep2"))

        episodes = memory.search_memories(memory_type=MemoryType.EPISODE)
        assert len(episodes) == 2

        facts = memory.search_memories(memory_type=MemoryType.ATOMIC_FACT)
        assert len(facts) == 1

    def test_delete_memory(self, memory):
        memory.save_memory(MemoryRecord(id="del1", type=MemoryType.EPISODE, content="x"))
        assert memory.delete_memory("del1") is True
        assert memory.get_memory("del1") is None

    def test_get_stats(self, memory):
        memory.save_memory(MemoryRecord(id="s1", type=MemoryType.EPISODE, content="x"))
        stats = memory.get_stats()
        assert stats["memories"] == 1


class TestUserProfile:
    """用户画像测试。"""

    @pytest.fixture
    def memory(self, tmp_path):
        return PersistentMemory(str(tmp_path / "test.db"))

    def test_save_and_get_profile(self, memory):
        profile = UserProfile(
            user_id="u1",
            products=["GitHub", "VS Code"],
            skill_level="intermediate",
        )
        memory.update_profile(profile)
        result = memory.get_profile("u1")
        assert result is not None
        assert "GitHub" in result.products
        assert result.skill_level == "intermediate"

    def test_update_profile(self, memory):
        profile = UserProfile(user_id="u2", products=["Docker"])
        memory.update_profile(profile)

        profile.products.append("Kubernetes")
        memory.update_profile(profile)

        result = memory.get_profile("u2")
        assert "Docker" in result.products
        assert "Kubernetes" in result.products

    def test_nonexistent_profile(self, memory):
        assert memory.get_profile("nonexistent") is None


class TestAgentCase:
    """成功案例测试。"""

    @pytest.fixture
    def memory(self, tmp_path):
        return PersistentMemory(str(tmp_path / "test.db"))

    def test_save_and_find_case(self, memory):
        case = AgentCase(
            question_pattern="创建仓库",
            steps=[{"order": 1, "action": "click", "selector": "#new-btn"}],
            url_pattern="github.com/*",
        )
        memory.save_case(case)

        found = memory.find_case("创建仓库", "github.com/dashboard")
        assert found is not None
        assert found.question_pattern == "创建仓库"

    def test_case_success_increment(self, memory):
        case = AgentCase(id="c1", question_pattern="test", steps=[])
        memory.save_case(case)
        memory.save_case(case)  # 重复保存

        # 查找后应该 success_count = 2
        found = memory.find_case("test")
        assert found is not None
        assert found.success_count >= 2

    def test_case_failure_record(self, memory):
        case = AgentCase(id="c2", question_pattern="fail_test", steps=[])
        memory.save_case(case)
        memory.record_case_failure("c2")

        stats = memory.get_stats()
        assert stats["cases"] == 1


class TestProfileExtractor:
    """用户画像提取测试。"""

    def test_extract_products(self):
        extractor = ProfileExtractor()
        messages = [
            {"content": "GitHub 怎么创建 PR？"},
            {"content": "VS Code 怎么安装扩展？"},
        ]
        profile = extractor.extract_from_conversation(messages)
        assert "GitHub" in profile.products
        assert "VS Code" in profile.products

    def test_extract_skill_level(self):
        extractor = ProfileExtractor()
        messages = [{"content": "怎么配置 CI/CD pipeline？"}]
        profile = extractor.extract_from_conversation(messages)
        assert profile.skill_level == "advanced"

    def test_extract_beginner(self):
        extractor = ProfileExtractor()
        messages = [{"content": "什么是 Docker？怎么入门？"}]
        profile = extractor.extract_from_conversation(messages)
        assert profile.skill_level == "beginner"

    def test_extract_from_page_event(self):
        extractor = ProfileExtractor()
        profile = UserProfile()
        profile = extractor.extract_from_page_event("https://github.com/settings", profile)
        assert "GitHub" in profile.products


class TestCaseExtractor:
    """案例提取测试。"""

    def test_extract_correct_feedback(self):
        extractor = CaseExtractor()
        case = extractor.extract_from_feedback(
            question="怎么创建仓库？",
            steps=[{"order": 1, "action": "click", "selector": "#new-btn"}],
            page_url="https://github.com/dashboard",
            is_correct=True,
        )
        assert case is not None
        assert case.question_pattern == "创建仓库"
        assert len(case.steps) == 1

    def test_extract_wrong_feedback(self):
        extractor = CaseExtractor()
        case = extractor.extract_from_feedback(
            question="怎么创建仓库？",
            steps=[],
            page_url="https://github.com/dashboard",
            is_correct=False,
        )
        assert case is None


class TestForesightExtractor:
    """前瞻预测测试。"""

    @pytest.mark.asyncio
    async def test_predict_after_create(self):
        extractor = ForesightExtractor()
        predictions = await extractor.predict(
            recent_questions=["GitHub 怎么创建仓库？"],
            current_url="https://github.com/new",
            products=["GitHub"],
        )
        assert len(predictions) > 0

    @pytest.mark.asyncio
    async def test_predict_on_settings_page(self):
        extractor = ForesightExtractor()
        predictions = await extractor.predict(
            recent_questions=[],
            current_url="https://github.com/settings",
            products=["GitHub"],
        )
        assert any("配置" in p for p in predictions)


class TestCleanup:
    """清理测试。"""

    @pytest.fixture
    def memory(self, tmp_path):
        return PersistentMemory(str(tmp_path / "test.db"))

    def test_cleanup_old_memories(self, memory):
        memory.save_memory(MemoryRecord(
            id="old",
            type=MemoryType.EPISODE,
            content="old",
            accessed_at=time.time() - 100 * 86400,  # 100 天前
            access_count=1,
        ))
        result = memory.cleanup(max_age_days=90)
        assert result["memories"] == 1
