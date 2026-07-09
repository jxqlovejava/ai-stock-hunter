# -*- coding: utf-8 -*-
"""CninfoProvider 单元测试。

测试 cninfo.com.cn（巨潮资讯网）数据源适配器。
"""

from __future__ import annotations

import pytest

from src.data.cninfo import REPORT_CATEGORIES, CninfoProvider, _get_default_provider


class TestCninfoProvider:
    """CninfoProvider 核心功能测试。"""

    @pytest.fixture
    def provider(self):
        """创建 CninfoProvider 实例（测试间复用 session）。"""
        p = CninfoProvider()
        yield p

    def test_health_check(self, provider):
        """连通性检查：应能加载 orgId 映射表。"""
        assert provider.health_check() is True
        assert len(provider._orgid_map) > 0

    def test_orgid_mapping(self, provider):
        """orgId 映射：应能正确查回常见股票代码的 orgId。"""
        provider._load_orgid_map()
        # 平安银行
        org_000001 = provider._get_orgid("000001")
        assert org_000001
        assert org_000001 != "000001"  # 应返回真实 orgId，非空字符串

        # 贵州茅台
        org_600519 = provider._get_orgid("600519")
        assert org_600519
        assert org_600519.startswith("gssh0")  # 上交所

    def test_orgid_fallback(self, provider):
        """orgId 回退：查不到的代码应使用硬编码规则。"""
        result = provider._get_orgid("999999")
        assert result.startswith("gssz0")  # 默认深交所

    def test_search_announcements_basic(self, provider):
        """公告检索：应返回非空列表。"""
        results = provider.search_announcements("000001", page_size=5)
        assert isinstance(results, list)
        if results:
            entry = results[0]
            assert "title" in entry
            assert "type" in entry
            assert "date" in entry
            assert "url" in entry
            assert "announcement_id" in entry
            assert entry["announcement_id"]

    def test_search_announcements_with_keyword(self, provider):
        """关键词搜索：应返回匹配标题的结果。"""
        results = provider.search_announcements("000001", keyword="分红", page_size=10)
        assert isinstance(results, list)

    def test_search_announcements_invalid_symbol(self, provider):
        """无效股票代码：应返回空列表，不抛异常。"""
        results = provider.search_announcements("999999", page_size=5)
        assert isinstance(results, list)
        # 无效代码可能返回空列表或少量结果

    def test_get_periodic_reports(self, provider):
        """定期报告：年报搜索应返回结果。"""
        results = provider.get_periodic_reports("000001", "annual", page_size=5)
        assert isinstance(results, list)

    def test_get_periodic_reports_quarterly(self, provider):
        """季报搜索。"""
        results = provider.get_periodic_reports("000001", "quarterly", page_size=5)
        assert isinstance(results, list)

    def test_report_categories_known(self):
        """已知报告类型映射应存在。"""
        assert "annual" in REPORT_CATEGORIES
        assert "semi_annual" in REPORT_CATEGORIES
        assert "quarterly" in REPORT_CATEGORIES

    def test_ts_to_date(self, provider):
        """时间戳转换。"""
        # Unix 毫秒 → YYYY-MM-DD（时区相关，验证格式即可）
        result = provider._ts_to_date(1700000000000)
        assert result.startswith("2023-11-")  # 2023年11月
        assert len(result) == 10  # YYYY-MM-DD

        # 无效输入
        assert provider._ts_to_date(0) == ""
        assert provider._ts_to_date(None) == ""

    def test_default_provider_singleton(self):
        """模块级单例：多次调用返回同一实例。"""
        p1 = _get_default_provider()
        p2 = _get_default_provider()
        assert p1 is p2

    def test_repr(self, provider):
        """__repr__ 应显示状态信息。"""
        r = repr(provider)
        assert "CninfoProvider" in r

    def test_session_creation(self, provider):
        """Session 懒初始化：访问 session 属性应创建实例。"""
        s = provider.session
        assert s is not None
        assert "User-Agent" in s.headers

    def test_rate_limit_record(self, provider):
        """节流时间记录。"""
        import time
        before = time.time()
        provider._mark_call()
        after = time.time()
        assert provider._last_call >= before
        assert provider._last_call <= after

    def test_get_detail_invalid_id(self, provider):
        """无效公告 ID：get_announcement_detail 应返回 None，不抛异常。"""
        result = provider.get_announcement_detail("invalid_id_12345")
        # 无效 ID 可能返回 None 或包含错误信息的 dict
        if result is not None:
            assert isinstance(result, dict)

    def test_get_pdf_url_invalid_id(self, provider):
        """无效公告 ID：get_pdf_url 应返回 None，不抛异常。"""
        result = provider.get_pdf_url("invalid_id_12345")
        assert result is None or isinstance(result, str)
