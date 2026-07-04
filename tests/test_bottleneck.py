# -*- coding: utf-8 -*-
"""瓶颈分析模块测试 — 借鉴 cyberagent 框架。"""

from __future__ import annotations


class TestBottleneck:
    def test_owner_classification(self):
        from src.industry.bottleneck import BottleneckType
        assert BottleneckType.OWNER.value == "owner"
        assert BottleneckType.ADJACENT.value == "adjacent"

    def test_supply_chain_layers(self):
        from src.industry.bottleneck import SupplyChainLayer
        assert len(list(SupplyChainLayer)) == 8

    def test_bottleneck_analysis_defaults(self):
        from src.industry.bottleneck import BottleneckAnalysis
        ba = BottleneckAnalysis(symbol="688256", name="寒武纪")
        assert ba.bottleneck_type.value == "none"
        assert not ba.is_bottleneck_play

    def test_should_avoid_parabolic(self):
        from src.industry.bottleneck import (
            BottleneckAnalysis, BottleneckType, PricingPosition,
        )
        ba = BottleneckAnalysis(
            symbol="TEST", name="测试",
            bottleneck_type=BottleneckType.NONE,
            pricing_position=PricingPosition.PARABOLIC,
        )
        assert ba.should_avoid

    def test_owner_is_bottleneck_play(self):
        from src.industry.bottleneck import BottleneckAnalysis, BottleneckType
        ba = BottleneckAnalysis(
            symbol="688256", name="寒武纪",
            bottleneck_type=BottleneckType.OWNER,
        )
        assert ba.is_bottleneck_play

    def test_score_map(self):
        from src.industry.bottleneck import BottleneckType
        scores = {
            BottleneckType.OWNER: 100, BottleneckType.ADJACENT: 65,
            BottleneckType.DERIVATIVE: 35, BottleneckType.NONE: 10,
        }
        assert scores[BottleneckType.OWNER] > scores[BottleneckType.ADJACENT]
        assert scores[BottleneckType.NONE] < scores[BottleneckType.DERIVATIVE]

    def test_sa_ladder(self):
        from src.industry.bottleneck import SA_LADDER
        assert len(SA_LADDER) == 5
        assert SA_LADDER[0][0].startswith("电力")


class TestSupplyChain:
    def test_ai_chain_has_8_nodes(self):
        from src.industry.supply_chain import AI_SEMICONDUCTOR
        assert len(AI_SEMICONDUCTOR) == 8

    def test_new_energy_chain(self):
        from src.industry.supply_chain import NEW_ENERGY
        assert len(NEW_ENERGY) >= 4

    def test_classify_known_stock(self):
        from src.industry.supply_chain import classify_stock
        node = classify_stock("300308")  # 中际旭创 - 光模块
        assert node is not None
        assert "光模块" in node.name

    def test_classify_unknown_stock(self):
        from src.industry.supply_chain import classify_stock
        node = classify_stock("999999")
        assert node is None

    def test_classify_cowos(self):
        from src.industry.supply_chain import classify_stock
        from src.industry.bottleneck import BottleneckType
        node = classify_stock("603005")  # 晶方科技 - CoWoS
        assert node is not None
        assert node.bottleneck_type == BottleneckType.OWNER

    def test_classify_transformer(self):
        from src.industry.supply_chain import classify_stock
        from src.industry.bottleneck import BottleneckType
        node = classify_stock("600089")  # 特变电工 - 变压器
        assert node is not None
        assert node.bottleneck_type == BottleneckType.OWNER


class TestL1BottleneckIntegration:
    def test_analyzer_includes_bottleneck(self):
        from src.routing.l1_analyze import L1Analyzer
        analyzer = L1Analyzer()
        report = analyzer.analyze(
            "300308", "中际旭创",
            {"pe_percentile": 40, "northbound": 1},
            [{"roe": 15}],
            {"pmi": 52, "erp": 5},
        )
        assert report.bottleneck_analysis is not None
        assert report.bottleneck_analysis.bottleneck_score > 50

    def test_analyzer_no_bottleneck_for_unknown(self):
        from src.routing.l1_analyze import L1Analyzer
        analyzer = L1Analyzer()
        report = analyzer.analyze(
            "600519", "贵州茅台",
            {"pe_percentile": 40, "northbound": 1},
            [{"roe": 25}],
        )
        # 茅台不在我们维护的半导体/新能源供应链中
        assert report.bottleneck_analysis is None
