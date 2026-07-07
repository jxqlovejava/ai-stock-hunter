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
def sample_valuation_result():
    """模拟估值分析结果。"""
    try:
        from src.valuation.schema import ValuationResult, ValuationPhase, ValuationSubScores
        return ValuationResult(
            symbol="600519",
            name="贵州茅台",
            composite_score=58.5,
            sub_scores=ValuationSubScores(
                pe_percentile_score=65.0,
                peg_score=60.0,
                industry_relative_score=50.0,
                pb_roe_match_score=55.0,
                dividend_yield_score=60.0,
                signals_available=4,
                confidence=0.85,
            ),
            phase=ValuationPhase.FAIR_VALUE,
            pe_ttm=25.5,
            pb=8.2,
            pe_percentile=35.0,
        )
    except ImportError:
        return None


@pytest.fixture
def sample_cycle_analysis():
    """模拟周期分析结果。"""
    try:
        from src.cycle.schema import CycleAnalysis, CyclePhase
        return CycleAnalysis(
            phase=CyclePhase.EXPANSION,
            confidence=0.80,
            pmi=53.5,
            pmi_trend="rising",
            industrial_production=7.2,
            gdp_growth=5.6,
            ppi=2.1,
            signals_available=4,
            cycle_score=85.0,
            cycle_adjustment_factor=1.1,
            preferred_sectors=["消费", "科技"],
            avoid_sectors=["公用事业"],
        )
    except ImportError:
        return None

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
