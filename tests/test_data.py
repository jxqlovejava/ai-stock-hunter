# -*- coding: utf-8 -*-
"""数据层单元测试。"""

from __future__ import annotations

import pytest

from src.data.schema import Financials, Quote
from src.data.cross_validator import validate_fundamentals, validate_price


class TestQuote:
    def test_create_quote(self):
        q = Quote(symbol="600519", name="贵州茅台", price=1200.0, source="guosen")
        assert q.symbol == "600519"
        assert q.price == 1200.0
        assert q.source == "guosen"

    def test_quote_defaults(self):
        q = Quote(symbol="000001", name="平安银行", price=10.0, source="akshare")
        assert q.change_pct == 0.0
        assert q.volume == 0
        assert q.turnover == 0.0
        assert q.high is None


class TestFinancials:
    def test_create_financials(self):
        f = Financials(
            symbol="600519",
            report_period="2025Q4",
            revenue=1.5e11,
            net_profit=7.5e10,
            source="guosen",
        )
        assert f.report_period == "2025Q4"
        assert f.revenue == 1.5e11

    def test_financials_nulls(self):
        f = Financials(symbol="688981", report_period="2024Q4", source="akshare")
        assert f.revenue is None
        assert f.net_profit is None


class TestCrossValidator:
    def test_validate_price_both_sources(self):
        gs = Quote(symbol="600519", name="茅台", price=1200.0, source="guosen")
        ak = Quote(symbol="600519", name="茅台", price=1198.0, source="akshare")
        result = validate_price(gs, ak)
        assert result["validated"] is True
        assert result["dispute"] is False
        assert result["diff_pct"] < 0.01  # ~0.17%

    def test_validate_price_dispute(self):
        gs = Quote(symbol="000001", name="平安银行", price=10.0, source="guosen")
        ak = Quote(symbol="000001", name="平安银行", price=9.0, source="akshare")
        result = validate_price(gs, ak)
        assert result["validated"] is True
        assert result["dispute"] is True  # 10% diff > 3% threshold
        assert result["diff_pct"] > 0.03

    def test_validate_price_single_source(self):
        gs = Quote(symbol="300750", name="宁德时代", price=200.0, source="guosen")
        result = validate_price(gs, None)
        assert result["validated"] is False
        assert result["dispute"] is False
        assert result["price"] == 200.0

    def test_validate_price_no_sources(self):
        result = validate_price(None, None)
        assert result["validated"] is False
        assert result["price"] is None

    def test_validate_fundamentals_single(self):
        from src.data.schema import FundamentalMetrics
        m = FundamentalMetrics(
            symbol="600519", name="茅台", pe_ttm=25.0, pb=8.0, roe=30.0,
            sources=["guosen"],
        )
        result = validate_fundamentals([m])
        assert result is not None
        assert result.pe_ttm == 25.0
        assert result.cross_validated is False

    def test_validate_fundamentals_multi(self):
        from src.data.schema import FundamentalMetrics
        m1 = FundamentalMetrics(
            symbol="600519", name="茅台", pe_ttm=25.0, pb=8.0, roe=30.0,
            sources=["guosen"],
        )
        m2 = FundamentalMetrics(
            symbol="600519", name="茅台", pe_ttm=25.5, pb=8.1, roe=30.0,
            sources=["akshare"],
        )
        result = validate_fundamentals([m1, m2])
        assert result is not None
        assert result.cross_validated is True
        assert result.dispute is False  # < 5% diff
