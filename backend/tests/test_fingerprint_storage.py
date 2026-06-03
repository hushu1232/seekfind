"""
求问 — FingerprintStorage 测试
==============================

测试指纹存储层：
  - save / find 基本操作
  - 模糊匹配
  - success_count 递增
  - fail_count 记录
  - 过期清理
  - 统计
  - 域名隔离
"""

import time

import pytest
from memory.fingerprint_storage import FingerprintStorage


class TestFingerprintStorage:
    """FingerprintStorage 单元测试。"""

    @pytest.fixture
    def storage(self, tmp_path):
        """创建临时存储。"""
        db_path = str(tmp_path / "test_fingerprints.db")
        return FingerprintStorage(db_path)

    def test_save_and_find_exact(self, storage):
        """保存后可通过精确描述查找。"""
        storage.save(
            url_pattern="github.com/settings",
            selector="#create-btn",
            description="创建项目按钮",
        )
        result = storage.find("https://github.com/dashboard", "创建项目按钮")
        assert result is not None
        assert result["selector"] == "#create-btn"
        assert result["match_score"] == 1.0

    def test_find_fuzzy_match(self, storage):
        """模糊匹配：描述不完全一致但相似。"""
        storage.save(
            url_pattern="github.com/settings",
            selector="#create-btn",
            description="创建项目按钮",
        )
        # 描述不完全一致，但相似度 >= 0.6
        result = storage.find("https://github.com/dashboard", "新建项目按钮")
        assert result is not None
        assert result["match_score"] >= 0.6
        assert result["selector"] == "#create-btn"

    def test_find_no_match(self, storage):
        """无匹配返回 None。"""
        result = storage.find("https://github.com/dashboard", "完全不相关的元素")
        assert result is None

    def test_find_wrong_domain(self, storage):
        """不同域名不匹配。"""
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://gitlab.com", "按钮")
        assert result is None

    def test_success_count_increment(self, storage):
        """重复保存递增 success_count。"""
        storage.save("github.com", "#btn", "按钮")
        storage.save("github.com", "#btn", "按钮")
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://github.com", "按钮")
        assert result is not None
        assert result["success_count"] == 3

    def test_record_failure(self, storage):
        """记录失败递增 fail_count。"""
        storage.save("github.com", "#btn", "按钮")
        result = storage.find("https://github.com", "按钮")
        assert result is not None

        storage.record_failure(result["id"])
        # 重新查找，检查 fail_count
        result2 = storage.find("https://github.com", "按钮")
        assert result2 is not None
        assert result2["fail_count"] == 1

    def test_cleanup_removes_old_bad_fingerprints(self, storage):
        """清理过期且失败多于成功的指纹。"""
        storage.save("github.com", "#old-btn", "旧按钮")
        # 手动设置为过期且失败多
        storage._conn.execute(
            "UPDATE fingerprints SET last_used_at = ?, fail_count = 10, success_count = 1",
            (time.time() - 31 * 86400,),
        )
        storage._conn.commit()

        deleted = storage.cleanup(max_age_days=30)
        assert deleted == 1

        # 确认已删除
        result = storage.find("https://github.com", "旧按钮")
        assert result is None

    def test_cleanup_keeps_good_fingerprints(self, storage):
        """清理保留成功多于失败的指纹。"""
        storage.save("github.com", "#good-btn", "好按钮")
        # 手动设置为过期但成功多
        storage._conn.execute(
            "UPDATE fingerprints SET last_used_at = ?, success_count = 10, fail_count = 1",
            (time.time() - 31 * 86400,),
        )
        storage._conn.commit()

        deleted = storage.cleanup(max_age_days=30)
        assert deleted == 0  # 不应删除

    def test_get_stats(self, storage):
        """统计信息。"""
        storage.save("github.com", "#btn1", "按钮1")
        storage.save("github.com", "#btn2", "按钮2")
        storage.save("github.com", "#btn3", "按钮3")
        # btn3 保存两次，success_count >= 2
        storage.save("github.com", "#btn3", "按钮3")

        stats = storage.get_stats()
        assert stats["total"] == 3
        assert stats["reliable"] == 1  # 只有 btn3 的 success_count >= 2

    def test_multiple_selectors_same_desc(self, storage):
        """同一描述可以有多个 selector。"""
        storage.save("github.com", "#btn-v1", "创建按钮")
        storage.save("github.com", ".create-btn-v2", "创建按钮")

        # 两个都应能查到
        result = storage.find("https://github.com", "创建按钮")
        assert result is not None
        # 应返回 success_count 最高的
        assert result["success_count"] >= 1

    def test_domain_extraction(self, storage):
        """域名提取。"""
        assert FingerprintStorage._extract_domain("https://github.com/settings") == "github.com"
        assert FingerprintStorage._extract_domain("http://docs.example.com:8080/guide") == "docs.example.com"
        assert FingerprintStorage._extract_domain("github.com") == "github.com"

    def test_xpath_stored(self, storage):
        """XPath 备选选择器存储。"""
        storage.save(
            url_pattern="github.com",
            selector="#btn",
            description="按钮",
            xpath="//button[@id='btn']",
        )
        result = storage.find("https://github.com", "按钮")
        assert result is not None
        assert result["xpath"] == "//button[@id='btn']"

    def test_attributes_stored(self, storage):
        """元素属性存储。"""
        storage.save(
            url_pattern="github.com",
            selector="#btn",
            description="按钮",
            tag_name="button",
            attributes={"class": "btn-primary", "data-testid": "create"},
        )
        result = storage.find("https://github.com", "按钮")
        assert result is not None
        assert result["tag_name"] == "button"
        assert result["attributes"]["class"] == "btn-primary"
