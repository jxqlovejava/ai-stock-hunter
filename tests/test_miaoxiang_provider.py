# -*- coding: utf-8 -*-
"""MiaoXiangProvider 单元测试。"""

import pytest

from src.data.miaoxiang_provider import MiaoXiangProvider, _find_value
from src.data.schema import Quote, Financials, NewsItem, RelatedParty, ScreeningResult


class TestMiaoXiangProvider:
    """MiaoXiangProvider 测试。"""

    def test_default_construction(self):
        """默认构造。"""
        provider = MiaoXiangProvider()
        assert provider is not None
        assert provider.source_name == "miaoxiang"

    def test_health_check(self):
        """health_check 返回布尔值。"""
        provider = MiaoXiangProvider()
        result = provider.health_check()
        assert isinstance(result, bool)

    def test_search_news_empty_without_key(self):
        """无有效 API Key 时 search_news 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        items = provider.search_news("test query")
        assert items == []

    def test_search_announcements_empty(self):
        """无 API Key 时 search_announcements 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        items = provider.search_announcements("600519")
        assert items == []

    def test_search_research_reports_empty(self):
        """无 API Key 时 search_research_reports 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        items = provider.search_research_reports("600519")
        assert items == []

    def test_get_related_parties_empty(self):
        """无 API Key 时 get_related_parties 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        parties = provider.get_related_parties("600519")
        assert parties == []

    def test_screen_stocks_empty(self):
        """无 API Key 时 screen_stocks 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        results = provider.screen_stocks("市盈率<20")
        assert results == []

    def test_screen_by_industry_empty(self):
        """无 API Key 时 screen_by_industry 返回空列表。"""
        provider = MiaoXiangProvider(api_key="")
        results = provider.screen_by_industry("新能源")
        assert results == []

    def test_moni_methods_return_none(self):
        """无 API Key 时 moni 方法返回 None。"""
        provider = MiaoXiangProvider(api_key="")
        assert provider.moni_get_positions() is None
        assert provider.moni_get_balance() is None
        assert provider.moni_get_orders() is None

    def test_cache_clear(self):
        """缓存清空。"""
        provider = MiaoXiangProvider(api_key="test")
        provider._cache_set("test", "value")
        provider.cache_clear()
        assert len(provider._cache) == 0


class TestQuoteParsing:
    """mx-data 响应 → Quote 解析。"""

    def test_parse_quote_from_raw_basic(self):
        """基本行情解析。"""
        raw = {
            "data": {
                "dataTableDTOList": [{
                    "entityName": "贵州茅台 (600519.SH)",
                    "table": {
                        "headName": ["2026-07-04"],
                        "f2": [1850.00],
                        "f3": [2.78],
                        "f5": [3500000],
                        "f6": [6475000000.0],
                        "f15": [1860.00],
                        "f16": [1830.00],
                        "f17": [1845.00],
                        "f18": [1800.00],
                    },
                    "nameMap": {
                        "f2": "最新价",
                        "f3": "涨跌幅",
                        "f5": "成交量",
                        "f6": "成交额",
                        "f15": "最高价",
                        "f16": "最低价",
                        "f17": "开盘价",
                        "f18": "前收盘价",
                    },
                    "indicatorOrder": ["f2", "f3"],
                }],
            },
        }
        quote = MiaoXiangProvider._parse_quote_from_raw(raw, "600519", "SH")
        assert quote is not None
        assert quote.symbol == "600519"
        assert quote.name == "贵州茅台"
        assert quote.price == 1850.0
        assert quote.change_pct == 2.78
        assert quote.source == "miaoxiang"

    def test_parse_quote_from_raw_empty(self):
        """空响应返回 None。"""
        assert MiaoXiangProvider._parse_quote_from_raw({}, "test", "SH") is None
        assert MiaoXiangProvider._parse_quote_from_raw(
            {"data": {"dataTableDTOList": []}}, "test", "SH"
        ) is None


class TestFinancialsParsing:
    """mx-data 响应 → Financials 解析。"""

    def test_parse_financials_from_raw_basic(self):
        """基本财务数据解析。"""
        raw = {
            "data": {
                "dataTableDTOList": [{
                    "entityName": "贵州茅台 (600519.SH)",
                    "table": {
                        "headName": ["2025Q4", "2024Q4", "2023Q4"],
                        "f1": [1500e8, 1400e8, 1300e8],
                        "f2": [747e8, 700e8, 650e8],
                    },
                    "nameMap": {
                        "f1": "营业总收入",
                        "f2": "归母净利润",
                    },
                    "indicatorOrder": ["f1", "f2"],
                }],
            },
        }
        fin_list = MiaoXiangProvider._parse_financials_from_raw(raw, "600519", 3)
        assert len(fin_list) == 3
        assert fin_list[0].symbol == "600519"
        assert fin_list[0].report_period == "2025Q4"
        assert fin_list[0].revenue == 1500e8
        assert fin_list[0].net_profit == 747e8
        assert fin_list[0].source == "miaoxiang"

    def test_parse_financials_empty(self):
        """空响应返回空列表。"""
        assert MiaoXiangProvider._parse_financials_from_raw({}, "test", 4) == []


class TestFindValue:
    """_find_value 工具函数测试。"""

    def test_exact_match(self):
        values = {"最新价": 100.0, "涨跌幅": 2.5}
        assert _find_value(values, ["最新价", "收盘价"]) == 100.0

    def test_fuzzy_match(self):
        values = {"最新价 (元)": 100.0}
        assert _find_value(values, ["最新价"]) == 100.0

    def test_no_match(self):
        values = {"最新价": 100.0}
        assert _find_value(values, ["最高价", "最低价"]) is None

    def test_empty_values(self):
        assert _find_value({}, ["最新价"]) is None


class TestSchemaDTOs:
    """Schema DTO 测试。"""

    def test_news_item_defaults(self):
        item = NewsItem(title="测试")
        assert item.title == "测试"
        assert item.source == ""
        assert item.secu_list == []
        assert item.provider == "miaoxiang-search"

    def test_related_party_defaults(self):
        party = RelatedParty(entity_name="测试股东")
        assert party.entity_name == "测试股东"
        assert party.stake_pct is None
        assert party.provider == "miaoxiang-data"

    def test_screening_result_defaults(self):
        result = ScreeningResult(symbol="600519")
        assert result.symbol == "600519"
        assert result.name == ""
        assert result.extra_fields == {}
        assert result.provider == "miaoxiang-xuangu"

    def test_news_item_full(self):
        item = NewsItem(
            title="贵州茅台公告",
            source="东方财富",
            date="2026-07-01",
            content="公告内容...",
            secu_list=[{"secuCode": "600519", "secuName": "贵州茅台"}],
        )
        assert item.title == "贵州茅台公告"
        assert item.source == "东方财富"
        assert len(item.secu_list) == 1
