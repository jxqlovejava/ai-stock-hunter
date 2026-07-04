# -*- coding: utf-8 -*-
"""共享测试 fixtures — 为所有测试提供统一的数据构造器。"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta


@pytest.fixture
def sample_quote() -> dict:
    """模拟行情数据 (贵州茅台 600519)。"""
    return {
        "symbol": "600519",
        "name": "贵州茅台",
        "close": 1680.50,
        "open": 1665.00,
        "high": 1695.00,
        "low": 1660.00,
        "volume": 2500000,
        "amount": 4.2e9,
        "change_pct": 0.93,
        "pe_ttm": 25.5,
        "pb": 8.2,
        "market_cap": 2.1e12,
        "northbound": 1,
        "pe_percentile": 35,
        "is_st": False,
        "is_star_st": False,
        "is_limit_up": False,
        "is_limit_down": False,
        "is_suspended": False,
        "listing_days": 5000,
        "_source": "mootdx",
    }


@pytest.fixture
def sample_financials() -> list[dict]:
    """模拟财务数据。"""
    return [
        {"roe": 28.5, "gross_margin": 0.92, "debt_ratio": 0.15, "revenue_growth": 0.18},
        {"roe": 30.1, "gross_margin": 0.91, "debt_ratio": 0.14, "revenue_growth": 0.20},
        {"roe": 31.2, "gross_margin": 0.93, "debt_ratio": 0.13, "revenue_growth": 0.16},
    ]


@pytest.fixture
def sample_macro() -> dict:
    """模拟宏观数据。"""
    return {
        "pmi": 50.5,
        "erp": 5.2,
        "m1_m2_gap": 1.5,
        "social_financing_growth": 7.2,
        "sf_trend": "stable",
        "lpr_direction": "stable",
        "dr007_position": "neutral",
        "_source": "akshare",
    }


@pytest.fixture
def sample_analysis_report() -> object:
    """模拟 L1 分析报告。"""
    try:
        from src.routing.l1_analyze import AnalysisReport
        return AnalysisReport(
            symbol="600519",
            name="贵州茅台",
            macro_score=55.0,
            value_score=78.0,
            quality_score=85.0,
            momentum_score=62.0,
            earnings_revision_score=58.0,
            sentiment_signal="NORMAL",
            confidence=0.82,
        )
    except ImportError:
        return None


@pytest.fixture
def sample_verdict() -> object:
    """模拟 L2 裁决。"""
    try:
        from src.routing.l2_judge import Verdict
        return Verdict(
            symbol="600519",
            score=78,
            confidence=0.82,
            recommendation="BUY",
            falsifiable=["如果宏观 PMI < 48，建议失效"],
            risks=["宏观环境偏空"],
        )
    except ImportError:
        return None


@pytest.fixture
def sample_source_citation():
    """模拟数据源引用。"""
    try:
        from src.data.source_citation import SourceCitation
        return SourceCitation(
            provider="mootdx",
            field="quote",
            fetch_timestamp=datetime.now(),
            confidence=0.85,
        )
    except ImportError:
        return None


@pytest.fixture
def mock_data_aggregator(mocker):
    """Mock DataAggregator 以隔离测试。"""
    try:
        mock = mocker.patch("src.data.aggregator.DataAggregator")
        mock_instance = mocker.MagicMock()
        mock.return_value = mock_instance
        return mock_instance
    except Exception:
        return None
