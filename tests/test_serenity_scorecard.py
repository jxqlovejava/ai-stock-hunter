# -*- coding: utf-8 -*-
"""Serenity 研究优先级打分卡与 workflow 测试。"""

from __future__ import annotations


class TestSerenityScorecard:
    def test_perfect_owner_like_scores_high(self):
        from src.industry.serenity_scorecard import score_from_ratings, VERDICT_TOP

        result = score_from_ratings(
            ticker="603005",
            company="晶方科技",
            factors={
                "demand_inflection": 5,
                "architecture_coupling": 5,
                "chokepoint_severity": 5,
                "supplier_concentration": 5,
                "expansion_difficulty": 5,
                "evidence_quality": 5,
                "valuation_disconnect": 5,
                "catalyst_timing": 5,
            },
        )
        assert result.final_score == 100.0
        assert result.verdict == VERDICT_TOP
        assert result.verdict_cn == "顶级研究优先"

    def test_penalties_reduce_score(self):
        from src.industry.serenity_scorecard import score_from_ratings

        base = score_from_ratings(
            factors={k: 4 for k in (
                "demand_inflection", "architecture_coupling", "chokepoint_severity",
                "supplier_concentration", "expansion_difficulty", "evidence_quality",
                "valuation_disconnect", "catalyst_timing",
            )},
        )
        penalized = score_from_ratings(
            factors={k: 4 for k in (
                "demand_inflection", "architecture_coupling", "chokepoint_severity",
                "supplier_concentration", "expansion_difficulty", "evidence_quality",
                "valuation_disconnect", "catalyst_timing",
            )},
            penalties={"hype_risk": 5, "dilution_financing": 3},
        )
        # 5*2 + 3*2 = 16 penalty
        assert penalized.final_score == round(base.final_score - 16, 2)
        assert penalized.penalty_points == 16.0

    def test_invalid_rating_raises(self):
        from src.industry.serenity_scorecard import score_from_ratings
        import pytest

        with pytest.raises(ValueError):
            score_from_ratings(factors={"demand_inflection": 6})

    def test_estimate_from_owner_higher_than_none(self):
        from src.industry.serenity_scorecard import estimate_from_bottleneck_type

        owner = estimate_from_bottleneck_type("owner")
        none = estimate_from_bottleneck_type("none")
        assert owner.final_score > none.final_score
        assert owner.final_score >= 70

    def test_template_has_all_factors(self):
        from src.industry.serenity_scorecard import (
            FACTOR_WEIGHTS, PENALTY_KEYS, template_dict,
        )

        t = template_dict("600519", "茅台")
        assert set(t["factors"]) == set(FACTOR_WEIGHTS)
        assert set(t["penalties"]) == set(PENALTY_KEYS)
        assert abs(sum(FACTOR_WEIGHTS.values()) - 100.0) < 1e-6

    def test_to_markdown_contains_score(self):
        from src.industry.serenity_scorecard import score_from_ratings, to_markdown

        r = score_from_ratings(
            ticker="T", company="C",
            factors={"chokepoint_severity": 5, "evidence_quality": 5},
        )
        md = to_markdown(r)
        assert "Final score" in md
        assert "T" in md


class TestSerenityWorkflow:
    def test_role_mapping(self):
        from src.industry.bottleneck import BottleneckType
        from src.industry.serenity_workflow import (
            SerenityRole, bottleneck_type_to_serenity_role,
        )

        assert bottleneck_type_to_serenity_role(BottleneckType.OWNER) == SerenityRole.CONTROLS
        assert bottleneck_type_to_serenity_role(BottleneckType.NONE) == SerenityRole.STORY_ONLY

    def test_evidence_mapping(self):
        from src.industry.bottleneck import EvidenceLevel
        from src.industry.serenity_workflow import (
            SerenityEvidenceStrength,
            evidence_level_to_serenity,
            tier_nature_to_serenity,
        )

        assert evidence_level_to_serenity(EvidenceLevel.CONFIRMED) == SerenityEvidenceStrength.STRONG
        assert tier_nature_to_serenity("T0", "fact") == SerenityEvidenceStrength.STRONG
        assert tier_nature_to_serenity("T3", "speculation") == SerenityEvidenceStrength.WEAK

    def test_theme_scan_format_and_validate(self):
        from src.industry.serenity_workflow import (
            CompanyResearchRank,
            LayerRanking,
            ThemeScanResult,
            format_theme_scan_report,
            validate_theme_scan_completeness,
        )

        result = ThemeScanResult(
            theme="A股AI半导体",
            opening_judgment="先排产业链层级，再排公司。",
            layer_rankings=[
                LayerRanking(1, "equipment_metrology", "设备/计量", "扩产硬约束"),
                LayerRanking(2, "materials_consumables", "材料/耗材", "复购卡点"),
            ],
            company_rankings=[
                CompanyResearchRank(
                    rank=1, symbol="002371", name="北方华创",
                    what_constrains="刻蚀/薄膜设备",
                    rank_reason="贴近晶圆厂扩产",
                    evidence="年报设备收入",
                    main_risk="订单波动",
                ),
            ],
            downgraded_hot_areas=["纯算力芯片叙事过热，估值拥挤"],
            next_checks=["查设备订单与产能利用率"],
            source_count=30,
            candidate_universe_size=25,
        )
        gaps = validate_theme_scan_completeness(result)
        assert gaps == []
        report = format_theme_scan_report(result)
        assert "先排产业链层级" in report or "主题深扫" in report
        assert "卡住的环节" in report
        assert "降级的热门方向" in report
        assert "下一步核验" in report

    def test_incomplete_theme_scan_flagged(self):
        from src.industry.serenity_workflow import ThemeScanResult, validate_theme_scan_completeness

        gaps = validate_theme_scan_completeness(ThemeScanResult(theme="x"))
        assert any("层排名" in g for g in gaps)
        assert any("公司" in g for g in gaps)
        assert any("降级" in g for g in gaps)

    def test_challenge_block(self):
        from src.industry.serenity_workflow import (
            SerenityEvidenceStrength,
            SerenityRole,
            format_challenge_block,
        )

        text = format_challenge_block(
            "300308", "中际旭创",
            what_constrains="光模块互连",
            chain_position="模组层",
            serenity_role=SerenityRole.SUPPLIES,
            evidence="年报收入结构",
            evidence_strength=SerenityEvidenceStrength.MEDIUM,
            failure_conditions=["光模块过剩"],
            next_checks=["查毛利率"],
            research_priority_score=72.0,
        )
        assert "卡点挑战" in text
        assert "300308" in text
        assert "光模块" in text


class TestBottleneckSerenityIntegration:
    def test_apply_serenity_defaults_on_owner(self):
        from src.industry.bottleneck import (
            BottleneckAnalysis, BottleneckType, SupplyChainLayer,
        )

        ba = BottleneckAnalysis(
            symbol="603005", name="晶方科技",
            core_business="先进封装",
            supply_chain_layer=SupplyChainLayer.PACKAGING,
            bottleneck_type=BottleneckType.OWNER,
            constraint_description="CoWoS 相关封装产能",
            bottleneck_score=100,
        )
        ba.apply_serenity_defaults()
        assert ba.serenity_role == "controls"
        assert ba.research_priority_score > 50
        assert ba.what_constrains
        assert len(ba.failure_conditions) >= 1
        assert len(ba.next_checks) >= 1

    def test_diagnosis_fills_serenity_fields(self):
        from src.routing.diagnosis import DiagnosisEngine

        analyzer = DiagnosisEngine()
        report = analyzer.analyze(
            "300308", "中际旭创",
            {"pe_percentile": 40, "northbound": 1},
            [{"roe": 15}],
            {"pmi": 52, "erp": 5},
        )
        assert report.bottleneck_analysis is not None
        ba = report.bottleneck_analysis
        assert ba.research_priority_score > 0
        assert ba.what_constrains
        assert ba.serenity_role in (
            "controls", "supplies", "benefits", "weak_control", "story_only",
        )
