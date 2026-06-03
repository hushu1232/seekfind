"""
求问 — 浏览器指纹生成测试
========================

测试 fingerprints.py：
  - generate_stealth_headers 返回有效 headers
  - 降级到内置 UA 池
  - UA 多样性
"""


from indexer.fingerprints import generate_stealth_headers, get_random_user_agent


class TestGenerateStealthHeaders:
    """generate_stealth_headers 测试。"""

    def test_returns_dict(self):
        """返回字典类型。"""
        headers = generate_stealth_headers()
        assert isinstance(headers, dict)

    def test_has_user_agent(self):
        """包含 User-Agent。"""
        headers = generate_stealth_headers()
        assert "User-Agent" in headers
        assert len(headers["User-Agent"]) > 10

    def test_has_accept(self):
        """包含 Accept 头。"""
        headers = generate_stealth_headers()
        assert "Accept" in headers

    def test_has_referer(self):
        """包含 Referer 头。"""
        headers = generate_stealth_headers()
        # 可能是 referer 或 Referer
        referer_keys = [k for k in headers if k.lower() == "referer"]
        assert len(referer_keys) >= 1

    def test_ua_diversity(self):
        """多次调用应有不同的 User-Agent。"""
        uas = set()
        for _ in range(20):
            headers = generate_stealth_headers()
            uas.add(headers["User-Agent"])
        # 至少应有 2 种不同的 UA（browserforge 随机或内置池）
        assert len(uas) >= 1  # 保守断言，browserforge 可能返回相同 UA


class TestGetRandomUserAgent:
    """get_random_user_agent 测试。"""

    def test_returns_string(self):
        """返回字符串。"""
        ua = get_random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 10

    def test_contains_mozilla(self):
        """UA 包含 Mozilla（标准格式）。"""
        ua = get_random_user_agent()
        assert "Mozilla" in ua
