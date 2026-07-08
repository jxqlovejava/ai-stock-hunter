# -*- coding: utf-8 -*-
"""测试选股筛选预设 — 5 种预设定义验证和 screen_by_preset 功能。"""

from __future__ import annotations

import pytest


class TestScreeningPresets:
    """测试 SCREENING_PRESETS 定义。"""

    def test_presets_loaded(self):
        """所有 5 种预设应已加载。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        expected = ["value", "growth", "quality", "short", "special-situation"]
        for preset_name in expected:
            assert preset_name in SCREENING_PRESETS, f"缺失预设: {preset_name}"

    def test_preset_has_required_fields(self):
        """每个预设应包含必需字段。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        for name, preset in SCREENING_PRESETS.items():
            assert preset.name, f"{name}: 缺少 name"
            assert preset.description, f"{name}: 缺少 description"
            assert preset.weight_overrides, f"{name}: 缺少 weight_overrides"
            assert preset.thresholds, f"{name}: 缺少 thresholds"
            assert isinstance(preset.adapters, list), f"{name}: adapters 应为 list"

    def test_preset_weights_sum_positive(self):
        """每个预设的权重应至少有一个 > 0。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        for name, preset in SCREENING_PRESETS.items():
            total = sum(preset.weight_overrides.values())
            assert total > 0, f"{name}: 权重全为 0"

    def test_value_preset_thresholds(self):
        """价值型预设阈值应合理。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        value = SCREENING_PRESETS["value"]
        assert value.thresholds["max_pe"] == 15
        assert value.thresholds["max_pb"] == 1.5
        assert value.thresholds["min_div_yield"] == 0.02
        assert value.thresholds["min_market_cap"] == 2e9

    def test_growth_preset_thresholds(self):
        """成长型预设阈值应合理。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        growth = SCREENING_PRESETS["growth"]
        assert growth.thresholds["min_revenue_growth"] == 0.15
        assert growth.thresholds["min_earnings_growth"] == 0.20
        assert growth.thresholds["min_roic"] == 0.15
        assert growth.thresholds["require_positive_pe"] is True

    def test_quality_preset_thresholds(self):
        """质量型预设阈值应合理。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        quality = SCREENING_PRESETS["quality"]
        assert quality.thresholds["min_roe"] == 0.15
        assert quality.thresholds["min_consecutive_profit_years"] == 5

    def test_short_preset_no_short_sell(self):
        """做空型预设应仅用于风险识别 (A 股限制)。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        short = SCREENING_PRESETS["short"]
        assert any("不做空" in a or "仅识别风险" in a for a in short.adapters), \
            "做空型预设必须声明 A 股不做空"

    def test_special_situation_adapters(self):
        """事件驱动预设应包含 A 股特定事件。"""
        from src.routing.l1_analyze import SCREENING_PRESETS
        ss = SCREENING_PRESETS["special-situation"]
        adapter_text = " ".join(ss.adapters)
        assert any(kw in adapter_text for kw in ["IPO", "重组", "回购", "定增", "股权激励"]), \
            "事件驱动应包含 A 股特定事件类型"


class TestQuickFilter:
    """测试快速筛选逻辑。"""

    def test_st_stock_filtered(self):
        """ST 股票应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]
        quote = {"is_st": True}
        assert analyzer._passes_quick_filter(quote, preset) is False

    def test_star_st_stock_filtered(self):
        """*ST 股票应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]
        quote = {"is_star_st": True}
        assert analyzer._passes_quick_filter(quote, preset) is False

    def test_small_market_cap_filtered(self):
        """市值低于门槛应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]  # min_market_cap = 2e9
        quote = {"market_cap": 1e9}  # 10 亿 < 20 亿
        assert analyzer._passes_quick_filter(quote, preset) is False

    def test_large_market_cap_passes(self):
        """市值超过门槛应通过 (且 PE 在阈值内)。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]
        quote = {"market_cap": 5e9, "pe_ttm": 12}  # 50 亿 > 20 亿, PE 12 < max 15
        assert analyzer._passes_quick_filter(quote, preset) is True

    def test_high_pe_filtered_in_value(self):
        """高 PE 在价值筛选中应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]
        quote = {"market_cap": 5e9, "pe_ttm": 50}  # PE 50 > max 15
        assert analyzer._passes_quick_filter(quote, preset) is False

    def test_negative_pe_filtered_in_growth(self):
        """负 PE 在成长筛选中应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["growth"]
        quote = {"market_cap": 1e10, "pe_ttm": -5}
        assert analyzer._passes_quick_filter(quote, preset) is False

    def test_null_quote_filtered(self):
        """空行情应被过滤。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        analyzer = DiagnosisEngine()
        preset = SCREENING_PRESETS["value"]
        assert analyzer._passes_quick_filter(None, preset) is False  # type: ignore
        assert analyzer._passes_quick_filter({}, preset) is False


class TestPresetScoreCalc:
    """测试预设评分计算。"""

    def test_calc_preset_score_value(self):
        """价值型评分应以价值因子为主。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        from src.routing.l1_analyze import AnalysisReport
        report = AnalysisReport(
            symbol="600519", name="贵州茅台",
            value_score=80, quality_score=70,
            momentum_score=50, macro_score=55,
        )
        preset = SCREENING_PRESETS["value"]
        score = DiagnosisEngine._calc_preset_score(report, preset)
        # 价值权重 0.45, 质量 0.25
        assert score > 0
        # 价值得分高 → 总评分高
        # 80*0.45 + 70*0.25 + 50*0.1 + 55*0.1 + 50*0.1 = 36+17.5+5+5.5+5 = 69
        assert 60 < score < 80

    def test_calc_preset_score_growth(self):
        """成长型评分应以质量和动量为主。"""
        from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS
        from src.routing.l1_analyze import AnalysisReport
        report = AnalysisReport(
            symbol="300750", name="宁德时代",
            value_score=40, quality_score=85,
            momentum_score=75, macro_score=55,
        )
        preset = SCREENING_PRESETS["growth"]
        score = DiagnosisEngine._calc_preset_score(report, preset)
        # 质量 0.4, 动量 0.3 → 高质量+高动量应得分高
        assert score > 50


class TestScreenByPreset:
    """测试 screen_by_preset 方法。"""

    def test_screen_value_empty_candidates(self):
        """空候选列表应返回空结果。"""
        from src.routing.diagnosis import DiagnosisEngine
        analyzer = DiagnosisEngine()
        results = analyzer.screen_by_preset("value", [])
        assert results == []

    def test_screen_unknown_preset_raises(self):
        """未知预设应抛出 ValueError。"""
        from src.routing.diagnosis import DiagnosisEngine
        analyzer = DiagnosisEngine()
        with pytest.raises(ValueError, match="未知预设"):
            analyzer.screen_by_preset("nonexistent", [])

    def test_screen_value_basic(self):
        """基本价值筛选 — 有合格候选。"""
        from src.routing.diagnosis import DiagnosisEngine
        analyzer = DiagnosisEngine()
        candidates = [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "quote": {"market_cap": 2.1e12, "pe_ttm": 12, "pe_percentile": 35},
                "financials": [{"roe": 28}],
            },
            {
                "symbol": "000858",
                "name": "五粮液",
                "quote": {"market_cap": 8e11, "pe_ttm": 14, "pe_percentile": 40},
                "financials": [{"roe": 22}],
            },
        ]
        results = analyzer.screen_by_preset("value", candidates, limit=5)
        assert len(results) > 0

    def test_screen_limit_respected(self):
        """limit 参数应被遵守。"""
        from src.routing.diagnosis import DiagnosisEngine
        analyzer = DiagnosisEngine()
        candidates = [
            {
                "symbol": f"00000{i}",
                "name": f"测试{i}",
                "quote": {"market_cap": 5e9, "pe_ttm": 10},
                "financials": [{"roe": 15}],
            }
            for i in range(10)
        ]
        results = analyzer.screen_by_preset("value", candidates, limit=3)
        assert len(results) <= 3

    def test_screen_results_sorted_by_score(self):
        """结果应按得分降序排列。"""
        from src.routing.diagnosis import DiagnosisEngine
        analyzer = DiagnosisEngine()
        candidates = [
            {
                "symbol": "000001",
                "name": "低分组",
                "quote": {"market_cap": 5e9, "pe_ttm": 14, "pe_percentile": 80, "northbound": 0},
                "financials": [{"roe": 5}],
            },
            {
                "symbol": "000002",
                "name": "高分组",
                "quote": {"market_cap": 5e9, "pe_ttm": 8, "pe_percentile": 20, "northbound": 1},
                "financials": [{"roe": 25}],
            },
        ]
        results = analyzer.screen_by_preset("value", candidates, limit=5)
        if len(results) >= 2:
            scores = [r[2] for r in results]
            assert scores == sorted(scores, reverse=True), f"未按得分降序: {scores}"
