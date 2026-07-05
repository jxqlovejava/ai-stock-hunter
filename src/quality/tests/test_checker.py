# -*- coding: utf-8 -*-
"""MultiAgentQualityChecker 测试 — 5 维度质量审查。"""

from datetime import datetime, timedelta

import pytest

from src.quality.checker import MultiAgentQualityChecker
from src.quality.schema import AgentRole, Severity


def _make_report(**overrides):
    """快速构造模拟 AnalysisReport 的 helper。"""
    from unittest.mock import MagicMock

    report = MagicMock()
    report.symbol = overrides.get("symbol", "600519")
    report.name = overrides.get("name", "测试股票")

    # 评分
    report.macro_score = overrides.get("macro_score", 50.0)
    report.value_score = overrides.get("value_score", 50.0)
    report.quality_score = overrides.get("quality_score", 50.0)
    report.momentum_score = overrides.get("momentum_score", 50.0)
    report.executive_score = overrides.get("executive_score", 50.0)
    report.valuation_score = overrides.get("valuation_score", 50.0)

    # 文本
    report.sentiment_signal = overrides.get("sentiment_signal", "NEUTRAL")
    report.bull_case = overrides.get("bull_case", "")
    report.bear_case = overrides.get("bear_case", "")
    report.bottlenecks = overrides.get("bottlenecks", [])
    report.upstream_risks = overrides.get("upstream_risks", [])
    report.executive_risks = overrides.get("executive_risks", [])

    # 溯源
    report.source_citations = overrides.get("source_citations", [])
    report.confidence = overrides.get("confidence", 0.7)
    report.data_freshness = overrides.get("data_freshness", datetime.now())
    report.alpha_profile = overrides.get("alpha_profile", None)

    return report


class TestDataFreshness:
    """数据新鲜度审查测试。"""

    def test_no_citations(self):
        c = MultiAgentQualityChecker()
        report = _make_report(source_citations=[])
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.DATA_FRESHNESS)
        assert v.severity == Severity.LOW
        assert "无数据溯源信息" in v.flags[0]

    def test_stale_data(self):
        from src.data.source_citation import SourceCitation

        old_time = datetime.now() - timedelta(hours=50)
        sc = SourceCitation(
            provider="mootdx", field="close_price",
            fetch_timestamp=old_time, data_freshness=timedelta(hours=1),
            confidence=0.85,
        )
        c = MultiAgentQualityChecker()
        report = _make_report(source_citations=[sc])
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.DATA_FRESHNESS)
        assert v.severity == Severity.HIGH

    def test_fresh_data(self):
        from src.data.source_citation import SourceCitation

        sc = SourceCitation(
            provider="mootdx", field="close_price",
            fetch_timestamp=datetime.now(),
            data_freshness=timedelta(hours=1),
            confidence=0.85,
        )
        c = MultiAgentQualityChecker()
        report = _make_report(source_citations=[sc])
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.DATA_FRESHNESS)
        assert v.passed
        assert v.score == 100


class TestConsistency:
    """内部一致性审查测试。"""

    def test_value_trap(self):
        c = MultiAgentQualityChecker()
        report = _make_report(value_score=80, quality_score=20)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert any("价值陷阱" in f for f in v.flags)

    def test_chase_risk(self):
        c = MultiAgentQualityChecker()
        report = _make_report(momentum_score=80, value_score=15)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert any("追涨" in f for f in v.flags)

    def test_all_scores_neutral(self):
        c = MultiAgentQualityChecker()
        report = _make_report(
            macro_score=50, value_score=50, quality_score=50,
            momentum_score=50, executive_score=50,
        )
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert any("集中" in f for f in v.flags)

    def test_executive_mismatch(self):
        c = MultiAgentQualityChecker()
        report = _make_report(
            executive_score=75,
            executive_risks=["高管减持", "董事会变动"],
        )
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert any("不匹配" in f for f in v.flags)

    def test_consistent_no_flags(self):
        c = MultiAgentQualityChecker()
        report = _make_report(
            macro_score=55, value_score=60, quality_score=65,
            momentum_score=55, executive_score=50,
        )
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert v.passed
        assert v.score == 100

    def test_score_out_of_bounds(self):
        c = MultiAgentQualityChecker()
        report = _make_report(value_score=150)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.CONSISTENCY)
        assert any("越界" in f for f in v.flags)


class TestLeakage:
    """未来信息泄露审查测试。"""

    def test_no_leakage(self):
        c = MultiAgentQualityChecker()
        report = _make_report()
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.LEAKAGE)
        assert v.passed
        assert v.score == 100

    def test_extreme_sentiment_stale_data(self):
        c = MultiAgentQualityChecker()
        report = _make_report(
            sentiment_signal="PANIC",
            data_freshness=datetime.now() - timedelta(hours=3),
        )
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.LEAKAGE)
        assert any("数据已过" in f for f in v.flags)


class TestInterpretability:
    """经济可解释性审查测试。"""

    def test_missing_bull_bear(self):
        c = MultiAgentQualityChecker()
        report = _make_report(bull_case="", bear_case="")
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.INTERPRETABILITY)
        assert any("多空双视角" in f for f in v.flags)

    def test_has_bull_bear(self):
        c = MultiAgentQualityChecker()
        from src.alpha.schema import (
            AlphaProfile, AlphaSource, NarrativeStage,
            NarrativeLifecycle, SourceTier,
        )

        alpha = AlphaProfile(
            source=AlphaSource(source_tier=SourceTier.PRIMARY),
            narrative=NarrativeStage(stage=NarrativeLifecycle.EMERGING),
            alpha_score=65,
            alpha_rationale="消费复苏 + 品牌护城河",
        )
        report = _make_report(
            bull_case="消费复苏驱动业绩增长",
            bear_case="宏观下行压制消费需求",
            alpha_profile=alpha,
            bottlenecks=["茅台镇产能瓶颈"],
        )
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.INTERPRETABILITY)
        assert v.passed
        assert v.score == 100

    def test_no_alpha(self):
        c = MultiAgentQualityChecker()
        report = _make_report()
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.INTERPRETABILITY)
        assert any("Alpha" in f or "alpha" in f for f in v.flags)


class TestSafety:
    """计算安全检查测试。"""

    def test_confidence_out_of_bounds(self):
        c = MultiAgentQualityChecker()
        report = _make_report(confidence=1.5)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.SAFETY)
        assert any("越界" in f for f in v.flags)

    def test_confidence_too_low(self):
        c = MultiAgentQualityChecker()
        report = _make_report(confidence=0.15)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.SAFETY)
        assert any("极低" in f for f in v.flags)

    def test_boundary_values(self):
        c = MultiAgentQualityChecker()
        report = _make_report(macro_score=0, value_score=100)
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.SAFETY)
        assert any("边界值" in f for f in v.flags)

    def test_few_citations(self):
        c = MultiAgentQualityChecker()
        report = _make_report(source_citations=[])
        result = c.check(report)
        v = next(r for r in result.verdicts if r.agent == AgentRole.SAFETY)
        assert any("不足" in f for f in v.flags)


class TestOverallReport:
    """综合报告测试。"""

    def test_perfect_report(self):
        """完美报告：所有检查通过。"""
        from src.data.source_citation import SourceCitation
        from src.alpha.schema import (
            AlphaProfile, AlphaSource, NarrativeStage,
            NarrativeLifecycle, SourceTier,
        )

        c = MultiAgentQualityChecker()
        # 3 条 fresh citations
        sc1 = SourceCitation(
            provider="mootdx", field="close_price",
            fetch_timestamp=datetime.now(),
            data_freshness=timedelta(hours=1),
            confidence=0.85,
        )
        sc2 = SourceCitation(
            provider="guosen", field="roe",
            fetch_timestamp=datetime.now(),
            data_freshness=timedelta(hours=24),
            confidence=0.90,
        )
        sc3 = SourceCitation(
            provider="eastmoney", field="pb",
            fetch_timestamp=datetime.now(),
            data_freshness=timedelta(hours=24),
            confidence=0.80,
        )
        alpha = AlphaProfile(
            source=AlphaSource(source_tier=SourceTier.PRIMARY),
            narrative=NarrativeStage(stage=NarrativeLifecycle.EMERGING),
            alpha_score=65,
            alpha_rationale="消费复苏 + 品牌护城河",
        )
        report = _make_report(
            bull_case="消费复苏驱动业绩增长",
            bear_case="宏观下行压制消费需求",
            source_citations=[sc1, sc2, sc3],
            alpha_profile=alpha,
            macro_score=55, value_score=60, quality_score=65,
            momentum_score=55, executive_score=55,
            bottlenecks=["供应瓶颈"],
        )
        result = c.check(report)
        assert result.passed
        assert result.overall_score >= 90
        assert result.critical_count == 0

    def test_broken_report(self):
        """坏报告：数据过期 + 价值陷阱 + 置信度越界。"""
        from src.data.source_citation import SourceCitation

        c = MultiAgentQualityChecker()
        old_time = datetime.now() - timedelta(hours=100)
        sc = SourceCitation(
            provider="mootdx", field="close_price",
            fetch_timestamp=old_time, data_freshness=timedelta(hours=1),
            confidence=0.85,
        )
        report = _make_report(
            value_score=85, quality_score=15,
            confidence=2.0,
            bull_case="", bear_case="",
            source_citations=[sc],
        )
        result = c.check(report)
        assert not result.passed
        assert result.critical_count >= 1 or result.high_count >= 1

    def test_verdicts_count(self):
        c = MultiAgentQualityChecker()
        report = _make_report()
        result = c.check(report)
        assert len(result.verdicts) == 5
        agent_roles = {v.agent for v in result.verdicts}
        assert agent_roles == set(AgentRole)

    def test_summary_output(self):
        c = MultiAgentQualityChecker()
        report = _make_report()
        result = c.check(report)
        s = result.summary()
        assert "质量审查" in s
        assert "600519" in s

    def test_to_dict(self):
        c = MultiAgentQualityChecker()
        report = _make_report()
        result = c.check(report)
        d = result.to_dict()
        assert d["symbol"] == "600519"
        assert "passed" in d
        assert len(d["verdicts"]) == 5
