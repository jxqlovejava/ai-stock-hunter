# -*- coding: utf-8 -*-
"""P3-3/P3-4 回归测试 — 情绪 0-100 整合评分维 + 数据新鲜度参与诊断评分加权。

覆盖:
- P3-3 _score_sentiment: 极端恐慌/贪婪方向断言 + 无数据中性 + guba 合成
- P3-4 _apply_freshness_weighting: 过期 citation → 对应维度评分 ×0.7
- 不误降权: 无 citation / 数据新鲜 / 无条件 guba citation 但无情绪数据
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.data.source_citation import make_citation
from src.routing.diagnosis import DiagnosisEngine, DiagnosisReport


# ---------------------------------------------------------------------------
# P3-3: 情绪维 0-100 整合评分（逆向指标）
# ---------------------------------------------------------------------------

class TestSentimentScore:
    """_score_sentiment 方向语义: 高分=恐慌/逆向看多, 低分=贪婪/逆向看空。"""

    def test_extreme_panic_scores_high(self):
        """大盘极端恐慌(score=0) → 情绪维高分(逆向看多)。"""
        s = DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_PANIC", "score": 0}
        )
        assert s >= 80

    def test_extreme_greed_scores_low(self):
        """大盘极端贪婪(score=100) → 情绪维低分(逆向看空)。"""
        s = DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_GREED", "score": 100}
        )
        assert s <= 20

    def test_neutral_scores_50(self):
        """中性(score=50) 且无股吧数据 → 50。"""
        s = DiagnosisEngine._score_sentiment({"level": "NORMAL", "score": 50})
        assert s == 50.0

    def test_no_data_neutral(self):
        """无任何情绪数据 → 50（不误判方向）。"""
        assert DiagnosisEngine._score_sentiment(None) == 50.0
        assert DiagnosisEngine._score_sentiment({}) == 50.0

    def test_guba_greed_pulls_down_panic_market(self):
        """股吧高热度偏多(贪婪) + 高热 → 情绪维被拉低但仍偏恐慌。"""
        guba = SimpleNamespace(heat_score=90.0, bull_bear_ratio=2.5, hot_titles=["x"])
        s = DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_PANIC", "score": 0}, guba
        )
        # 大盘逆向 100 占 0.7 + 股吧逆向(ratio2.5→逆向20) 占 0.3 = 76
        assert 50 < s <= 100
        assert s < DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_PANIC", "score": 0}
        )

    def test_low_heat_pulls_toward_neutral(self):
        """股吧热度低 → 情绪方向信号弱，向中性 50 收缩。"""
        guba_low_heat = SimpleNamespace(heat_score=10.0, bull_bear_ratio=0.3, hot_titles=[])
        guba_high_heat = SimpleNamespace(heat_score=90.0, bull_bear_ratio=0.3, hot_titles=[])
        low = DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_PANIC", "score": 0}, guba_low_heat
        )
        high = DiagnosisEngine._score_sentiment(
            {"level": "EXTREME_PANIC", "score": 0}, guba_high_heat
        )
        assert low < high
        assert low > 50.0  # 仍偏恐慌方向，但被压低

    def test_analyze_sets_sentiment_score(self):
        """analyze 全流程把情绪维评分写入 report.sentiment_score。"""
        report = DiagnosisEngine().analyze(
            "000001", "平安银行",
            sentiment={"level": "EXTREME_PANIC", "score": 0},
        )
        assert report.sentiment_score >= 80
        assert "情绪状态(逆向)" in report.dimension_synthesis


# ---------------------------------------------------------------------------
# P3-4: 数据新鲜度参与诊断评分加权
# ---------------------------------------------------------------------------

def _stale(field: str, data_type: str = "realtime_quote", provider: str = "mootdx"):
    """构造一条已过期的 citation（100h 偏移，覆盖最长 24h 新鲜度类型）。"""
    c = make_citation(provider=provider, field=field, data_type=data_type)
    c.fetch_timestamp = datetime.now() - timedelta(hours=100)
    assert not c.is_fresh
    return c


def _fresh(field: str, data_type: str = "realtime_quote", provider: str = "mootdx"):
    """构造一条新鲜的 citation。"""
    return make_citation(provider=provider, field=field, data_type=data_type)


class TestFreshnessWeighting:
    """过期 citation → 对应维度评分 ×0.7。"""

    def test_stale_quote_downweights_value_quality_momentum(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.value_score, report.quality_score, report.momentum_score = 80.0, 70.0, 60.0
        report.macro_score = 50.0
        report.source_citations = [_stale("quote")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.value_score == pytest.approx(80.0 * 0.7)
        assert report.quality_score == pytest.approx(70.0 * 0.7)
        assert report.momentum_score == pytest.approx(60.0 * 0.7)
        # 无对应 citation 的维度不受影响
        assert report.macro_score == 50.0
        assert any("[STALE]" in g for g in report.data_gaps)

    def test_stale_macro_downweights_only_macro(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.macro_score, report.value_score = 80.0, 60.0
        report.source_citations = [_stale("macro", data_type="macro_indicator")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.macro_score == pytest.approx(80.0 * 0.7)
        assert report.value_score == 60.0

    def test_stale_financials_downweights_value_quality(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.value_score, report.quality_score = 90.0, 85.0
        report.momentum_score = 70.0
        report.source_citations = [_stale("financials", data_type="financials")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.value_score == pytest.approx(90.0 * 0.7)
        assert report.quality_score == pytest.approx(85.0 * 0.7)
        assert report.momentum_score == 70.0  # financials 不支撑动量

    def test_stale_executive_downweights_executive(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.executive_score = 75.0
        report.source_citations = [_stale("executive", data_type="executive", provider="miaoxiang-data-executive")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.executive_score == pytest.approx(75.0 * 0.7)

    def test_stale_guba_downweights_sentiment_when_data_present(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.sentiment_score = 80.0
        report.guba_heat_score = 60.0
        report.source_citations = [_stale("guba_sentiment", data_type="guba_sentiment", provider="guba")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.sentiment_score == pytest.approx(80.0 * 0.7)


class TestNoMisweighting:
    """无 citation / 数据新鲜 / 无条件 citation 无情绪数据 → 不误降权。"""

    def test_fresh_citation_no_downweight(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.value_score, report.macro_score = 80.0, 70.0
        report.source_citations = [
            _fresh("quote"), _fresh("macro", data_type="macro_indicator"),
        ]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.value_score == 80.0
        assert report.macro_score == 70.0
        assert report.data_gaps == []

    def test_no_citation_no_downweight(self):
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.value_score, report.quality_score = 80.0, 70.0
        report.source_citations = []
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.value_score == 80.0
        assert report.quality_score == 70.0

    def test_unconditional_guba_citation_no_data_no_downweight(self):
        """guba_sentiment citation 无条件生成；无情绪数据时过期也不降权情绪维。"""
        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.sentiment_score = 50.0
        report.guba_heat_score = 0.0
        report.guba_bull_bear_ratio = None
        report.source_citations = [_stale("guba_sentiment", data_type="guba_sentiment", provider="guba")]
        DiagnosisEngine._apply_freshness_weighting(report)
        assert report.sentiment_score == 50.0
