# -*- coding: utf-8 -*-
"""测试 Alpha Lens 核心引擎 — 信息来源层级、共识-现实缺口、叙事生命周期。"""

from __future__ import annotations

import pytest


class TestAlphaSource:
    """测试 AlphaSource DTO 和信息来源层级判定。"""

    def test_primary_source_detection(self):
        """一手材料应被识别为 PRIMARY tier。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        source = lens.classify_source_tier([
            "财报原文 2024年报",
            "电话会记录 Q4 Earnings Call",
            "巨潮公告 重大事项",
        ])
        assert source.source_tier.value == "primary"
        assert source.originality_score > 60
        assert source.noise_ratio < 0.3
        assert len(source.primary_sources) >= 2

    def test_consensus_noise_detection(self):
        """全网刷屏的二手信息应被识别为 noise tier。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        source = lens.classify_source_tier([
            "微博大V: 这家公司太牛了",
            "小红书推荐: 爆款股票",
            "抖音股评: 下一个十倍股",
            "股吧热帖: 冲啊",
        ])
        assert source.source_tier.value == "noise"
        assert source.originality_score < 40
        assert source.noise_ratio > 0.3
        assert source.alpha_potential < 30

    def test_mixed_sources(self):
        """混合来源应有合理判定。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        source = lens.classify_source_tier([
            "财报原文 Q1",
            "券商研报: 行业分析",
            "微博大V: 短期看好",
        ])
        assert source.source_tier.value in ("secondary", "tertiary")
        assert 0.2 <= source.noise_ratio <= 0.6

    def test_empty_sources(self):
        """空来源列表应有默认处理。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        source = lens.classify_source_tier([])
        assert source.confidence < 0.5
        assert source.originality_score <= 50

    def test_alpha_potential_property(self):
        """alpha_potential 应在 0-100 范围内。"""
        from src.alpha.schema import AlphaSource, SourceTier
        source = AlphaSource(
            source_tier=SourceTier.PRIMARY,
            originality_score=90,
            interpretation_depth=85,
            noise_ratio=0.1,
        )
        assert 50 <= source.alpha_potential <= 100

        noise_source = AlphaSource(
            source_tier=SourceTier.CONSENSUS_NOISE,
            originality_score=15,
            interpretation_depth=20,
            noise_ratio=0.9,
        )
        assert noise_source.alpha_potential < 30


class TestConsensusGap:
    """测试共识-现实缺口检测。"""

    def test_panic_market_gap(self):
        """恐慌市场 + 叙事强度高 → 可能被低估。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        gap = lens.detect_consensus_gap(
            market_narrative="AI算力过剩，GPU需求崩溃",
            narrative_intensity=0.8,
            logical_flaws=[
                "未区分战略放弃 vs 少量试水",
                "忽略供不应求下的套利逻辑",
                "把一个局部事件放大成宏大叙事",
            ],
            contrarian_evidence=[
                "三大云厂商 CapEx 指引仍在上调",
                "台积电 CoWoS 产能利用率 100%",
            ],
            sentiment_extreme="PANIC",
        )
        assert gap.gap_score >= 50
        assert gap.is_market_wrong
        assert gap.mispricing_direction == "undervalued"
        assert gap.exaggeration_score > 50

    def test_neutral_market_no_gap(self):
        """中性情绪 + 无逻辑漏洞 → 无显著缺口。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        gap = lens.detect_consensus_gap(
            market_narrative="茅台增长稳定",
            narrative_intensity=0.3,
            sentiment_extreme="NEUTRAL",
        )
        assert gap.gap_score < 40
        assert not gap.is_market_wrong

    def test_greed_market_overvalued(self):
        """贪婪市场 → 可能被高估。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        gap = lens.detect_consensus_gap(
            market_narrative="这是下一个十倍股，确定性极强",
            narrative_intensity=0.9,
            logical_flaws=["估值已透支3年增长", "忽略竞争格局变化"],
            sentiment_extreme="GREED",
        )
        assert gap.mispricing_direction == "overvalued"
        assert gap.exaggeration_score > 50

    def test_alpha_opportunity_messages(self):
        """不同缺口状态应有不同 Alpha 机会描述。"""
        from src.alpha.schema import ConsensusGap
        gap1 = ConsensusGap(gap_score=75, mispricing_direction="undervalued", confidence=0.8)
        assert "买入" in gap1.alpha_opportunity

        gap2 = ConsensusGap(gap_score=75, mispricing_direction="overvalued", confidence=0.8)
        assert "卖出" in gap2.alpha_opportunity

        gap3 = ConsensusGap(gap_score=20, mispricing_direction="neutral", confidence=0.7)
        assert "有效" in gap3.alpha_opportunity


class TestNarrativeStage:
    """测试叙事生命周期定位。"""

    def test_dormant_stage(self):
        """低讨论量 + 低估反映 → DORMANT。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        stage = lens.locate_narrative_stage(
            discussion_volume=5,
            discussion_growth_rate=0,
            institutional_attention=5,
            retail_attention=2,
            valuation_reflected=0.1,
        )
        assert stage.stage.value == "dormant"
        assert stage.is_entry_zone

    def test_emerging_stage(self):
        """低讨论量但增长 + 机构先于散户 → EMERGING。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        stage = lens.locate_narrative_stage(
            discussion_volume=15,
            discussion_growth_rate=10,
            institutional_attention=35,
            retail_attention=10,
            valuation_reflected=0.3,
        )
        assert stage.stage.value == "emerging"
        assert stage.is_entry_zone
        assert stage.early_signal_score > 30

    def test_crowded_stage(self):
        """高讨论量 + 增长停滞 + 估值充分 → CROWDED。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        stage = lens.locate_narrative_stage(
            discussion_volume=85,
            discussion_growth_rate=-2,    # 负增长
            institutional_attention=25,
            retail_attention=90,          # 散户主导
            valuation_reflected=0.9,
        )
        assert stage.stage.value == "crowded"
        assert stage.crowded_signal_score > 50
        assert stage.position_cap_pct == 0.0

    def test_consensus_stage(self):
        """高讨论量 + 散户主导 → CONSENSUS。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        stage = lens.locate_narrative_stage(
            discussion_volume=65,
            discussion_growth_rate=8,
            institutional_attention=30,
            retail_attention=70,
            valuation_reflected=0.7,
        )
        assert stage.stage.value == "consensus"
        assert stage.position_cap_pct <= 5.0

    def test_position_caps(self):
        """各叙事阶段应有合理的仓位上限。"""
        from src.alpha.schema import NarrativeStage, NarrativeLifecycle
        caps = {
            NarrativeLifecycle.DORMANT: 5.0,
            NarrativeLifecycle.EMERGING: 15.0,
            NarrativeLifecycle.SPREADING: 10.0,
            NarrativeLifecycle.CONSENSUS: 5.0,
            NarrativeLifecycle.CROWDED: 0.0,
            NarrativeLifecycle.FADING: 0.0,
        }
        for stage_enum, expected_cap in caps.items():
            stage = NarrativeStage(stage=stage_enum)
            assert stage.position_cap_pct == expected_cap, \
                f"Expected cap {expected_cap} for {stage_enum}, got {stage.position_cap_pct}"

    def test_action_hints(self):
        """每个阶段都应有操作提示。"""
        from src.alpha.schema import NarrativeStage, NarrativeLifecycle
        for stage_enum in NarrativeLifecycle:
            stage = NarrativeStage(stage=stage_enum)
            assert len(stage.action_hint) > 5, \
                f"Missing action hint for {stage_enum}"

    def test_institutional_flow_correction(self):
        """大资金流向应修正叙事阶段。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        stage = lens.locate_narrative_stage(
            discussion_volume=40,  # spreading range
            discussion_growth_rate=5,
            institutional_attention=50,
            retail_attention=60,
            valuation_reflected=0.5,
            large_position_changes={
                "institutional": 10,  # 机构增持
                "retail": -5,          # 散户减持
            },
        )
        # 机构增持+散户减持 → 可能修正为 EMERGING
        assert stage.stage.value in ("emerging", "spreading")


class TestAlphaProfile:
    """测试 AlphaProfile 综合 DTO。"""

    def test_has_alpha_true(self):
        """高 Alpha 评分 + 高置信度 → has_alpha=True。"""
        from src.alpha.schema import AlphaProfile, AlphaDecayStatus
        profile = AlphaProfile(
            alpha_score=72,
            alpha_confidence=0.8,
            decay_status=AlphaDecayStatus.FRESH,
        )
        assert profile.has_alpha

    def test_has_alpha_false_low_confidence(self):
        """低置信度 → has_alpha=False。"""
        from src.alpha.schema import AlphaProfile, AlphaDecayStatus
        profile = AlphaProfile(
            alpha_score=72,
            alpha_confidence=0.5,
            decay_status=AlphaDecayStatus.FRESH,
        )
        assert not profile.has_alpha

    def test_is_priced_in(self):
        """衰减状态 DECAYED/GONE → is_priced_in=True。"""
        from src.alpha.schema import AlphaProfile, AlphaDecayStatus
        profile = AlphaProfile(decay_status=AlphaDecayStatus.DECAYED)
        assert profile.is_priced_in

        fresh = AlphaProfile(decay_status=AlphaDecayStatus.FRESH)
        assert not fresh.is_priced_in

    def test_summary_property(self):
        """summary 应包含关键信息。"""
        from src.alpha.schema import AlphaProfile
        profile = AlphaProfile(
            alpha_score=65,
            key_differentiator="市场低估了直销占比提升的影响",
        )
        summary = profile.summary
        assert "65" in summary
        assert "dormant" in summary  # default stage


class TestAlphaLensAnalyze:
    """测试 AlphaLens.analyze() 主入口。"""

    def test_full_analysis_panic_market(self):
        """全面分析 — 恐慌市场 + 一手材料 + 逻辑漏洞。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        profile = lens.analyze(
            symbol="600519",
            news_sources=["财报原文 Q4", "电话会记录"],
            market_narrative="茅台增长到顶",
            narrative_intensity=0.7,
            logical_flaws=["忽略直销占比从30%提升至55%", "未区分量价拆分"],
            contrarian_evidence=["i茅台日均销售创新高"],
            sentiment_extreme="PANIC",
            discussion_volume=25,
            discussion_growth_rate=12,
            institutional_attention=40,
            retail_attention=15,
            valuation_reflected=0.4,
        )
        assert profile.alpha_score > 0
        assert 0 <= profile.alpha_score <= 100
        assert profile.source.source_tier.value == "primary"
        assert profile.consensus_gap.gap_score > 0
        assert len(profile.alpha_rationale) > 10
        assert len(profile.key_differentiator) > 5
        assert profile.alpha_confidence > 0

    def test_full_analysis_noise_market(self):
        """噪音市场 — 二手信息 + 无缺口。"""
        from src.alpha.lens import AlphaLens
        lens = AlphaLens()
        profile = lens.analyze(
            symbol="000001",
            news_sources=["微博大V推荐", "抖音股评"],
            market_narrative="银行股大涨",
            narrative_intensity=0.8,
            sentiment_extreme="GREED",
            discussion_volume=70,
            discussion_growth_rate=5,
            institutional_attention=20,
            retail_attention=80,
            valuation_reflected=0.85,
        )
        assert profile.source.source_tier.value == "noise"
        assert not profile.has_alpha  # 噪音源 + 高拥挤

    def test_decay_tracking(self):
        """第二次分析应有衰减追踪。"""
        from src.alpha.lens import AlphaLens
        from datetime import datetime, timedelta
        lens = AlphaLens()
        # 首次检测
        p1 = lens.analyze(symbol="600519")
        # 模拟衰减后的再次检测
        p1.first_detected = datetime.now() - timedelta(days=45)
        p2 = lens.analyze(
            symbol="600519",
            existing_profile=p1,
        )
        assert p2.days_since_detection > 0
        assert p2.decay_status.value in ("aging", "decayed", "gone")


class TestAlphaMonitor:
    """测试 AlphaMonitor 衰减监控。"""

    def test_track_new_signal(self):
        """首次追踪应创建记录。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile
        monitor = AlphaMonitor()
        profile = AlphaProfile(alpha_score=75)
        record = monitor.track("600519", profile)
        assert record.symbol == "600519"
        assert record.alpha_score == 75
        assert record.peak_alpha_score == 75

    def test_track_updates_existing(self):
        """再次追踪应更新记录。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile
        monitor = AlphaMonitor()
        monitor.track("600519", AlphaProfile(alpha_score=75))
        record = monitor.track("600519", AlphaProfile(alpha_score=60))
        assert record.peak_alpha_score == 75  # peak 不变
        assert record.alpha_score == 60       # 当前更新

    def test_detect_crowding(self):
        """检测拥挤信号。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile, NarrativeStage, NarrativeLifecycle
        monitor = AlphaMonitor()
        monitor.track("600519", AlphaProfile(alpha_score=60))
        is_crowded, msg = monitor.detect_crowding(
            "600519",
            discussion_volume=80,
            discussion_growth_rate=25,
            retail_attention=75,
            institutional_attention=20,
        )
        assert is_crowded  # 高讨论量 + 高增速 + 散户远高于机构

    def test_summary_includes_key_info(self):
        """摘要应包含评分、状态、叙事阶段。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile
        monitor = AlphaMonitor()
        monitor.track("600519", AlphaProfile(alpha_score=65))
        summary = monitor.summary("600519")
        assert "600519" in summary
        assert "65" in summary

    def test_list_active(self):
        """列出活跃信号。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile, AlphaDecayStatus
        monitor = AlphaMonitor()
        monitor.track("A", AlphaProfile(alpha_score=75))
        monitor.track("B", AlphaProfile(alpha_score=30))  # 低于默认阈值
        active = monitor.list_active(min_score=40)
        assert len(active) == 1
        assert active[0].symbol == "A"

    def test_compute_decay_velocity(self):
        """计算衰减速度。"""
        from src.alpha.monitor import AlphaMonitor
        from src.alpha.schema import AlphaProfile
        from datetime import datetime, timedelta
        monitor = AlphaMonitor()
        profile = AlphaProfile(alpha_score=75)
        monitor.track("600519", profile)
        # Mock history with decay
        record = monitor._signals["600519"]
        record.history = [
            (datetime.now() - timedelta(days=10), 75),
            (datetime.now() - timedelta(days=5), 65),
            (datetime.now(), 55),
        ]
        velocity = monitor.compute_decay_velocity("600519")
        assert velocity > 0  # 衰减中


class TestAlphaAttribution:
    """测试 Alpha 归因引擎。"""

    def test_decompose_return_alpha_driven(self):
        """Alpha 驱动型收益 — Alpha > Beta。"""
        from src.alpha.attribution import AlphaAttribution
        attr = AlphaAttribution()
        m, s, a, r = attr.decompose_return(
            total_return_pct=100.0,
            market_return_pct=5.0,
            sector_return_pct=8.0,
            stock_beta=1.0,
        )
        assert a > 50  # Alpha 应该很大
        assert a > m  # Alpha > 市场 Beta

    def test_decompose_return_beta_driven(self):
        """Beta 驱动型收益 — Beta > Alpha。"""
        from src.alpha.attribution import AlphaAttribution
        attr = AlphaAttribution()
        m, s, a, r = attr.decompose_return(
            total_return_pct=10.0,
            market_return_pct=12.0,
            sector_return_pct=5.0,
            stock_beta=1.2,
        )
        assert a < 0  # Alpha 应为负（跑输大盘）

    def test_evaluate_alpha_quality_emerging_entry(self):
        """EMERGING 阶段买入 → 时机质量高。"""
        from src.alpha.attribution import AlphaAttribution
        from src.alpha.schema import AlphaProfile, NarrativeStage, NarrativeLifecycle, SourceTier, AlphaSource
        attr = AlphaAttribution()
        profile = AlphaProfile(
            source=AlphaSource(
                source_tier=SourceTier.PRIMARY,
                originality_score=90,
                interpretation_depth=85,
            ),
            narrative=NarrativeStage(stage=NarrativeLifecycle.EMERGING),
        )
        sq, tq, zq, oq = attr.evaluate_alpha_quality(entry_profile=profile)
        assert tq > 70  # 时机质量高
        assert sq > 60  # 来源质量高

    def test_evaluate_alpha_quality_noise_entry(self):
        """噪音来源 + CONSENSUS 阶段买入 → 质量低。"""
        from src.alpha.attribution import AlphaAttribution
        from src.alpha.schema import AlphaProfile, NarrativeStage, NarrativeLifecycle, SourceTier, AlphaSource
        attr = AlphaAttribution()
        profile = AlphaProfile(
            source=AlphaSource(
                source_tier=SourceTier.CONSENSUS_NOISE,
                originality_score=15,
            ),
            narrative=NarrativeStage(stage=NarrativeLifecycle.CONSENSUS),
        )
        sq, tq, zq, oq = attr.evaluate_alpha_quality(entry_profile=profile)
        assert tq < 40  # 时机差
        assert oq < 50  # 整体质量低

    def test_full_attribution_report(self):
        """完整归因报告生成。"""
        from src.alpha.attribution import AlphaAttribution
        from src.alpha.schema import (
            AlphaProfile, NarrativeStage, NarrativeLifecycle,
            SourceTier, AlphaSource, ConsensusGap,
        )
        attr = AlphaAttribution()

        entry = AlphaProfile(
            source=AlphaSource(
                source_tier=SourceTier.PRIMARY,
                originality_score=85,
                interpretation_depth=80,
            ),
            consensus_gap=ConsensusGap(
                gap_score=65,
                mispricing_direction="undervalued",
                confidence=0.75,
            ),
            narrative=NarrativeStage(
                stage=NarrativeLifecycle.EMERGING,
                early_signal_score=70,
            ),
            alpha_score=72,
        )

        exit_p = AlphaProfile(
            narrative=NarrativeStage(
                stage=NarrativeLifecycle.CONSENSUS,
                crowded_signal_score=75,
            ),
        )

        report = attr.attribute(
            symbol="600519",
            total_return_pct=474.0,
            market_return_pct=30.0,
            sector_return_pct=50.0,
            stock_beta=1.0,
            entry_profile=entry,
            exit_profile=exit_p,
            position_sizing="overweight",
            holding_period_days=180,
        )

        assert report.is_alpha_driven
        assert report.alpha_return_pct > 0
        assert report.alpha_quality_score > 50
        assert len(report.key_insights) > 0
        assert len(report.alpha_sources) > 0

    def test_alpha_sources_identification(self):
        """Alpha 来源识别。"""
        from src.alpha.attribution import AlphaAttribution
        from src.alpha.schema import (
            AlphaProfile, SourceTier, AlphaSource, ConsensusGap,
            NarrativeStage, NarrativeLifecycle,
        )
        attr = AlphaAttribution()

        profile = AlphaProfile(
            source=AlphaSource(
                source_tier=SourceTier.PRIMARY,
                originality_score=85,
                interpretation_depth=75,
            ),
            consensus_gap=ConsensusGap(
                gap_score=65,
                mispricing_direction="undervalued",
                confidence=0.8,
            ),
            narrative=NarrativeStage(
                stage=NarrativeLifecycle.EMERGING,
                early_signal_score=65,
            ),
        )

        sources = attr._identify_alpha_sources(profile)
        assert any("一手信息" in s for s in sources)
        assert any("深度理解" in s or "共识偏差" in s or "叙事早期" in s for s in sources)


class TestPipelineIntegration:
    """测试 Alpha Lens 在全链路中的集成。"""

    def test_l1_report_with_alpha(self):
        """L1 AnalysisReport 携带 AlphaProfile。"""
        from src.routing.l1_analyze import L1Analyzer
        from src.alpha.schema import AlphaProfile
        l1 = L1Analyzer()
        alpha = AlphaProfile(alpha_score=65)
        report = l1.analyze("600519", "茅台", alpha_profile=alpha)
        assert report.alpha_profile is not None
        assert report.alpha_profile.alpha_score == 65

    def test_l2_verdict_with_alpha_multiplier(self):
        """L2 Verdict 包含 Alpha 乘数和理由。"""
        from src.routing.l1_analyze import L1Analyzer, AnalysisReport
        from src.routing.l2_judge import L2Judge
        from src.alpha.schema import (
            AlphaProfile, AlphaSource, SourceTier,
            ConsensusGap, NarrativeStage, NarrativeLifecycle,
        )

        # 高 Alpha profile
        high_alpha = AlphaProfile(
            source=AlphaSource(
                source_tier=SourceTier.PRIMARY,
                originality_score=85,
                interpretation_depth=80,
            ),
            consensus_gap=ConsensusGap(
                gap_score=60,
                mispricing_direction="undervalued",
                confidence=0.75,
            ),
            narrative=NarrativeStage(stage=NarrativeLifecycle.EMERGING),
            alpha_score=72,
            alpha_rationale="信息来源一手性强；市场共识可能存在偏差；叙事处于逻辑成型期",
        )

        l1 = L1Analyzer()
        report = l1.analyze(
            "600519", "茅台",
            quote={"pe_percentile": 30},
            financials=[{"roe": 20}],
            alpha_profile=high_alpha,
        )

        l2 = L2Judge()
        verdict = l2.judge(report)

        assert verdict.alpha_multiplier > 1.0  # 高 Alpha → 乘数 > 1
        assert len(verdict.alpha_rationale) > 0

    def test_l2_verdict_with_low_alpha(self):
        """低 Alpha → 乘数 < 1。"""
        from src.routing.l1_analyze import L1Analyzer
        from src.routing.l2_judge import L2Judge
        from src.alpha.schema import (
            AlphaProfile, AlphaSource, SourceTier,
            NarrativeStage, NarrativeLifecycle,
        )

        low_alpha = AlphaProfile(
            source=AlphaSource(source_tier=SourceTier.CONSENSUS_NOISE),
            narrative=NarrativeStage(stage=NarrativeLifecycle.CROWDED),
            alpha_score=25,
        )

        l1 = L1Analyzer()
        report = l1.analyze(
            "000001", "平安银行",
            quote={"pe_percentile": 50},
            financials=[{"roe": 10}],
            alpha_profile=low_alpha,
        )

        l2 = L2Judge()
        verdict = l2.judge(report)

        assert verdict.alpha_multiplier < 1.0  # 低 Alpha → 乘数 < 1

    def test_l3_signal_alpha_timing(self):
        """L3 TradeSignal 包含 Alpha 时序信息。"""
        from src.routing.l1_analyze import L1Analyzer
        from src.routing.l2_judge import L2Judge
        from src.routing.l3_trade import L3Trader
        from src.alpha.schema import (
            AlphaProfile, AlphaSource, SourceTier,
            ConsensusGap, NarrativeStage, NarrativeLifecycle,
        )

        alpha = AlphaProfile(
            source=AlphaSource(source_tier=SourceTier.PRIMARY),
            consensus_gap=ConsensusGap(
                gap_score=60,
                mispricing_direction="undervalued",
                confidence=0.75,
            ),
            narrative=NarrativeStage(
                stage=NarrativeLifecycle.EMERGING,
                early_signal_score=70,
            ),
            alpha_score=72,
            alpha_rationale="信息来源一手性强；市场共识可能存在偏差；叙事处于逻辑成型期（最佳Alpha窗口）",
        )

        l1 = L1Analyzer()
        report = l1.analyze(
            "600519", "茅台",
            quote={"pe_percentile": 30},
            financials=[{"roe": 20}],
            alpha_profile=alpha,
        )

        l2 = L2Judge()
        verdict = l2.judge(report)

        l3 = L3Trader()
        signal = l3.generate_signal(verdict)

        assert len(signal.alpha_timing) > 0

    def test_l4_alpha_decay_check(self):
        """L4 风控检测 Alpha 衰减。"""
        from src.routing.l3_trade import TradeSignal
        from src.routing.l4_risk import L4RiskOfficer

        l4 = L4RiskOfficer()
        signal = TradeSignal(
            symbol="600519",
            action="HOLD",
            target_weight=0.1,
        )

        # Alpha 快速衰减的 portfolio
        portfolio = {
            "alpha_tracker": {
                "decay_velocity": 1.5,
                "days_since_detection": 45,
                "is_crowded": True,
                "narrative_stage": "crowded",
            }
        }

        risk = l4.check(signal, portfolio)
        assert any("DECAY" in v or "CROWDED" in v or "STAGE_SHIFT" in v or "EXIT" in v
                   for v in risk.violations)


class TestAlphaDecayStatus:
    """测试 AlphaDecayStatus 枚举。"""

    def test_status_values(self):
        """状态值正确。"""
        from src.alpha.schema import AlphaDecayStatus
        assert AlphaDecayStatus.FRESH.value == "fresh"
        assert AlphaDecayStatus.AGING.value == "aging"
        assert AlphaDecayStatus.DECAYED.value == "decayed"
        assert AlphaDecayStatus.GONE.value == "gone"
        assert AlphaDecayStatus.CROWDED_OUT.value == "crowded"


class TestSourceTier:
    """测试 SourceTier 枚举。"""

    def test_tier_values(self):
        """层级值正确。"""
        from src.alpha.schema import SourceTier
        assert SourceTier.PRIMARY.value == "primary"
        assert SourceTier.SECONDARY.value == "secondary"
        assert SourceTier.TERTIARY.value == "tertiary"
        assert SourceTier.CONSENSUS_NOISE.value == "noise"


class TestNarrativeLifecycle:
    """测试 NarrativeLifecycle 枚举。"""

    def test_lifecycle_values(self):
        """生命周期值正确。"""
        from src.alpha.schema import NarrativeLifecycle
        assert NarrativeLifecycle.DORMANT.value == "dormant"
        assert NarrativeLifecycle.EMERGING.value == "emerging"
        assert NarrativeLifecycle.CROWDED.value == "crowded"
        assert NarrativeLifecycle.FADING.value == "fading"
