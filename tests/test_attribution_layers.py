# -*- coding: utf-8 -*-
"""P3-1 三层归因分层 (执行/配置/逻辑) — 单元测试。

覆盖:
  ① 三层归因数据结构可用且默认向后兼容
  ② 给定驱动因素正确分层 (执行/配置/逻辑 各一)
  ③ 高层 (逻辑层) 被推翻所需证据级别更高
  ④ build_driver_factors 自动分层 + formatter 向后兼容
"""

from __future__ import annotations

import pytest

from src.routing.attribution import (
    classify_layer,
    dominant_layer,
    format_layer_attributions,
    layerize_drivers,
)
from src.routing.attribution_formatter import format_attribution_result
from src.routing.attribution_types import (
    AttributionDataPoint,
    AttributionLayer,
    AttributionResult,
    DriverFactor,
    LayerAttribution,
)
from src.data.source_citation import (
    NATURE_FACT,
    SOURCE_TIER_T1,
    SOURCE_TIER_T2,
    SourceCitation,
)


# ────────────────────────────────────────────────────────
# ① 数据结构可用 + 默认向后兼容
# ────────────────────────────────────────────────────────

def test_layer_enum_members_and_rank():
    """AttributionLayer 包含三层, 层位序正确。"""
    assert AttributionLayer.EXECUTION.value == "EXECUTION"
    assert AttributionLayer.CONFIGURATION.value == "CONFIGURATION"
    assert AttributionLayer.LOGIC.value == "LOGIC"
    assert AttributionLayer.EXECUTION.rank == 1
    assert AttributionLayer.CONFIGURATION.rank == 2
    assert AttributionLayer.LOGIC.rank == 3


def test_layer_attribution_dataclass_defaults():
    """LayerAttribution 可用默认值构造, 未被覆盖时按 layer 取默认推翻级别。"""
    la = LayerAttribution(
        layer=AttributionLayer.EXECUTION,
        driver="追高买入致套牢",
        evidence="盘中冲高后快速回落",
    )
    assert la.confidence == 0.0
    assert la.overturn_evidence_level == 0  # 0 表示按 layer 默认
    assert la.effective_overturn_level() == 1
    assert not la.is_primary

    la_logic = LayerAttribution(layer=AttributionLayer.LOGIC, driver="x", evidence="y")
    assert la_logic.effective_overturn_level() == 3


def test_attribution_result_backward_compatible_default():
    """AttributionResult 默认构造时 layer_attributions 为空 (向后兼容)。"""
    r = AttributionResult()
    assert r.layer_attributions == []


def test_formatter_consumes_result_with_new_field():
    """attribution_formatter.format_attribution_result 消费含新字段的 result 不报错。"""
    r = AttributionResult(symbol="600089", name="XX公司", price_change_pct=-3.5)
    out = format_attribution_result(r)
    assert "个股涨跌归因" in out


def test_formatter_renders_layer_attributions_block():
    """format_attribution_result 渲染三层归因块 (执行/配置/逻辑 + 主导层)。"""
    r = _make_result_with_three_layers()
    layerize_drivers(r)
    out = format_attribution_result(r)
    assert "三层归因分层" in out
    assert "执行层" in out
    assert "配置层" in out
    assert "投资逻辑层" in out
    assert "主导层" in out
    assert "推翻所需证据级别" in out
    assert "业绩不及预期" in out  # 主因 (投资逻辑层) 的驱动名
    # 主因标记列
    assert "主因" in out


def test_formatter_no_layer_field_backward_compatible():
    """无 layer_attributions 时输出确定性提示且不报错 (向后兼容)。"""
    r = AttributionResult(symbol="600089", name="XX公司", price_change_pct=-3.5)
    out = format_attribution_result(r)
    assert "三层归因分层" in out
    assert "未计算" in out


# ────────────────────────────────────────────────────────
# ② 给定驱动因素正确分层 (执行/配置/逻辑 各一)
# ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "driver_name, expected",
    [
        ("买点差追高致套牢", AttributionLayer.EXECUTION),
        ("追高买入后止损未执行", AttributionLayer.EXECUTION),
        ("盘中冲高回落恐慌抛售", AttributionLayer.EXECUTION),
        ("重仓单一标的仓位过重", AttributionLayer.CONFIGURATION),
        ("仓位过重未分散集中持仓", AttributionLayer.CONFIGURATION),
        ("杠杆过高融资补仓节奏混乱", AttributionLayer.CONFIGURATION),
        ("Q2 业绩不及预期核心假设被证伪", AttributionLayer.LOGIC),
        ("基本面恶化盈利修正下调", AttributionLayer.LOGIC),
        ("行业景气下行需求萎缩", AttributionLayer.LOGIC),
    ],
)
def test_classify_layer_by_keyword(driver_name, expected):
    """关键词分层: 执行/配置/逻辑 各驱动因素正确归层。"""
    assert classify_layer(driver_name) is expected


def test_classify_layer_by_category_fallback():
    """无关键词命中时按数据点 category 映射 (technical→执行, capital_flow→配置)。"""
    assert (
        classify_layer("主力资金净流出 2000 万", category="capital_flow")
        is AttributionLayer.CONFIGURATION
    )
    assert (
        classify_layer("K线跌破 60 日均线", category="technical")
        is AttributionLayer.EXECUTION
    )
    # 无关键词无 category → 中性兜底层 (避免把执行问题升级成逻辑问题)
    assert classify_layer("盘面数据异常波动") is AttributionLayer.CONFIGURATION


def _make_point(category: str, description: str, tier: str = SOURCE_TIER_T1) -> AttributionDataPoint:
    return AttributionDataPoint(
        category=category,
        description=description,
        source_citation=SourceCitation(
            provider="test",
            field=category,
            source_tier=tier,
            nature=NATURE_FACT,
            confidence=0.8,
        ),
    )


def _make_result_with_three_layers() -> AttributionResult:
    """构造含 执行/配置/逻辑 三类驱动因素 + 对应数据点的 AttributionResult。"""
    r = AttributionResult(symbol="600089", name="XX公司", price_change_pct=-3.5)
    r.raw_data_points = [
        _make_point("technical", "行情: 买点差追高 盘中冲高回落 涨跌 -3.21%"),
        _make_point("capital_flow", "个股资金流: 重仓未分散 主力净额 -200万"),
        _make_point("announcement", "公告: 业绩不及预期 盈利下滑"),
    ]
    r.drivers = [
        DriverFactor(name="业绩不及预期", weight=0.5, tier=SOURCE_TIER_T1, nature=NATURE_FACT, freshness="fresh", is_primary=True),
        DriverFactor(name="重仓未分散", weight=0.3, tier=SOURCE_TIER_T2, nature=NATURE_FACT, freshness="fresh"),
        DriverFactor(name="买点差追高", weight=0.2, tier=SOURCE_TIER_T2, nature=NATURE_FACT, freshness="fresh"),
    ]
    return r


def test_layerize_drivers_correct_layers():
    """给定驱动因素 (执行/配置/逻辑各一) 正确分层, 且与 drivers 同序。"""
    r = _make_result_with_three_layers()
    layers = layerize_drivers(r)

    assert len(layers) == 3
    assert layers[0].layer is AttributionLayer.LOGIC  # 业绩不及预期 (主因)
    assert layers[1].layer is AttributionLayer.CONFIGURATION  # 重仓未分散
    assert layers[2].layer is AttributionLayer.EXECUTION  # 买点差追高

    # 写回 result.layer_attributions
    assert r.layer_attributions == layers
    # 主因标记传递
    assert layers[0].is_primary is True
    # 证据从数据点提取
    assert "业绩不及预期" in layers[0].evidence


def test_dominant_layer():
    """dominant_layer 返回置信度权重最大的层。"""
    r = _make_result_with_three_layers()
    layerize_drivers(r)
    assert dominant_layer(r) is AttributionLayer.LOGIC
    assert dominant_layer(AttributionResult()) is None


# ────────────────────────────────────────────────────────
# ③ 高层 (逻辑层) 被推翻所需证据级别更高
# ────────────────────────────────────────────────────────

def test_overturn_evidence_level_ordering():
    """推翻所需证据级别: LOGIC > CONFIGURATION > EXECUTION。"""
    assert (
        AttributionLayer.LOGIC.overturn_evidence_level
        > AttributionLayer.CONFIGURATION.overturn_evidence_level
        > AttributionLayer.EXECUTION.overturn_evidence_level
    )
    assert AttributionLayer.EXECUTION.overturn_evidence_level == 1
    assert AttributionLayer.CONFIGURATION.overturn_evidence_level == 2
    assert AttributionLayer.LOGIC.overturn_evidence_level == 3


def test_layer_attribution_effective_level_respects_layer():
    """单条归因的 effective_overturn_level 按 layer 升高, 显式指定可覆盖。"""
    execution = LayerAttribution(
        layer=AttributionLayer.EXECUTION, driver="买点差", evidence="e"
    )
    logic = LayerAttribution(
        layer=AttributionLayer.LOGIC, driver="业绩证伪", evidence="e"
    )
    assert logic.effective_overturn_level() > execution.effective_overturn_level()
    assert execution.effective_overturn_level() == 1
    explicit = LayerAttribution(
        layer=AttributionLayer.EXECUTION, driver="d", evidence="e",
        overturn_evidence_level=2,
    )
    assert explicit.effective_overturn_level() == 2


def test_format_layer_attributions_renders_layers():
    """格式化辅助函数渲染三层分层块, 含层名与主导层。"""
    r = _make_result_with_three_layers()
    layerize_drivers(r)
    out = format_layer_attributions(r)
    assert "三层归因分层" in out
    assert "执行层" in out
    assert "配置层" in out
    assert "投资逻辑层" in out
    assert "主导层" in out
    # 空结果也有确定性输出
    assert "未计算" in format_layer_attributions(AttributionResult())


# ────────────────────────────────────────────────────────
# ④ build_driver_factors 自动分层 (端到端)
# ────────────────────────────────────────────────────────

def test_build_driver_factors_auto_layers():
    """build_driver_factors 后 layer_attributions 自动填充。"""
    from src.routing.attribution import AttributionEngine

    r = AttributionResult(symbol="600089", name="XX公司", price_change_pct=-3.5)
    r.raw_data_points = [
        _make_point("announcement", "公告: 业绩预告不及预期"),
        _make_point("technical", "行情: 冲高回落 涨跌 -3.21%"),
    ]
    engine = AttributionEngine()
    engine.build_driver_factors(
        r,
        primary="业绩预告不及预期",
        secondary=["盘中冲高回落"],
        noise=[],
        causality_chain="业绩低于预期 → 盈利修正 → 抛压",
    )

    assert len(r.drivers) > 0
    assert len(r.layer_attributions) == len(r.drivers)
    # 主因 → 投资逻辑层
    assert r.layer_attributions[0].layer is AttributionLayer.LOGIC
    assert r.layer_attributions[0].is_primary is True
    # 次因 (盘中冲高回落) → 执行层
    secondary_layers = {
        la.layer for la in r.layer_attributions
        if la.driver == "盘中冲高回落"
    }
    assert secondary_layers == {AttributionLayer.EXECUTION}


def test_layerize_drivers_empty_is_idempotent():
    """无 drivers 时 layerize_drivers 返回空列表且幂等。"""
    r = AttributionResult()
    assert layerize_drivers(r) == []
    assert r.layer_attributions == []
