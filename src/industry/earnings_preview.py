# -*- coding: utf-8 -*-
"""先行指标 → 业绩测算模型。

基于公开高频数据（锂盐价格、出货量指引、下游需求数据、成本端价格），
在财报正式发布前测算碳酸锂企业（赣锋锂业/天齐锂业等）的季度业绩。

核心公式:
  Q2锂盐毛利 ≈ Q2出货量 × (Q2加权均价 − 锂精矿成本 − 加工费)
  Q2电池利润 ≈ Q2电池出货(GWh) × 单Wh净利
  Q2归母净利润 ≈ (锂盐毛利 × (1−少数股东比例) + 电池利润) × (1−有效税率) + 其他收益

数据支撑:
  - 锂盐价格: LithiumPriceTracker (东财期货 + SMM)
  - Q1基线: mootdx 财务快照 / 新浪三表 / 公司公告
  - 出货量: 公司电话会指引 + 海关进出口交叉验证
  - 下游需求: 中汽协NEV销量 / 动力电池装车量 (需手动输入)

用法:
    from src.data.commodity import LithiumPriceTracker
    from src.industry.earnings_preview import EarningsPreviewModel

    tracker = LithiumPriceTracker()
    basket = tracker.get_lithium_basket()

    model = EarningsPreviewModel.for_ganfeng()  # 赣锋锂业预设参数
    result = model.preview_q2(basket)
    print(f"Q2归母净利预测: {result.net_profit_estimate:.1f}亿")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.commodity.schemas import LithiumBasket

logger = logging.getLogger(__name__)

# ── 赣锋锂业 (002460) 关键参数 ──────────────────────────────────────────
# 来源: Q1 2026 财报 + 电话会指引 + 券商研报 (美银/东吴)


@dataclass
class LithiumCompanyParams:
    """碳酸锂企业关键经营参数。"""

    name: str = ""
    code: str = ""

    # Q1 已知数据 (来自财报, 金额单位: 亿元)
    q1_net_profit: float = 0.0  # Q1 归母净利润 (亿元)
    q1_revenue: float = 0.0  # Q1 营收 (亿元)
    q1_shipment_kt: float = 0.0  # Q1 锂盐出货量 (万吨LCE)
    q1_battery_gwh: float = 0.0  # Q1 电池出货 (GWh)

    # Q2 出货量预估 (来自公司指引 + 行业数据交叉验证, 单位: 万吨/GWh)
    q2_shipment_kt: float = 0.0  # Q2 锂盐出货量 (万吨LCE)
    q2_battery_gwh: float = 0.0  # Q2 电池出货 (GWh)

    # 全年指引
    full_year_shipment_kt: float = 0.0  # 全年锂盐出货指引 (万吨LCE)
    full_year_battery_gwh: float = 0.0  # 全年电池出货指引 (GWh)

    # 成本结构
    self_supply_ratio: float = 0.70  # 资源自供率 (0-1)
    processing_fee_per_ton: float = 25000  # 加工费 (元/吨)
    minority_interest_ratio: float = 0.15  # 少数股东损益占比
    effective_tax_rate: float = 0.15  # 有效税率
    realization_factor: float = 0.88  # 现货→实际售价折算系数 (长协M-1滞后+产品结构折扣)
    other_cost_per_ton: float = 35000  # 其他成本 SG&A+R&D+运输+折旧+税费附加 (元/吨)
    # 注: Q1校准前为15000, Q1实际毛利率29.7%反推全成本~9.5万/吨,
    # 扣除矿成本~4.9万后 other_cost ~4.6万; 取整3.5万保守估计

    # 非经常性损益
    non_recurring_ratio: float = 0.12  # 非经常性损益占归母净利比 (公允价值变动+政府补贴)

    # 电池业务
    battery_profit_per_wh: float = 0.025  # 电池单Wh净利 (元/Wh)

    # 产品结构权重
    carbonate_weight: float = 0.65  # 碳酸锂收入占比
    hydroxide_weight: float = 0.35  # 氢氧化锂收入占比

    # 其他常量
    usd_cny_rate: float = 7.25  # USD/CNY
    wan_ton_to_ton: float = 10000  # 万吨→吨


# ── 赣锋锂业 预设参数 ──────────────────────────────────────────────────
# Q1 2026 实际数据: 归母净利 18.4亿, 营收 ~135亿
# 出货: Q1约5万吨LCE, Q2指引5.5万吨
# 电池: Q1约10GWh, 全年指引40-45GWh


def _ganfeng_params_q2() -> LithiumCompanyParams:
    """赣锋锂业 (002460) Q2预测参数。基于Q1财报+电话会指引。"""
    return LithiumCompanyParams(
        name="赣锋锂业",
        code="002460",
        # Q1 实际 (基线)
        q1_net_profit=18.4,
        q1_revenue=135.0,
        q1_shipment_kt=5.0,  # 万吨
        q1_battery_gwh=10.0,
        # Q2 预估
        q2_shipment_kt=5.5,  # 万吨
        q2_battery_gwh=12.0,
        # 全年指引
        full_year_shipment_kt=23.0,
        full_year_battery_gwh=43.0,
        # 成本 (Q1实际校准: 毛利率29.7% → other_cost≈3.5万)
        self_supply_ratio=0.70,
        processing_fee_per_ton=25000,
        minority_interest_ratio=0.15,
        effective_tax_rate=0.15,
        battery_profit_per_wh=0.025,
        other_cost_per_ton=35000,
        non_recurring_ratio=0.23,  # Q1非经常性占比高 (2.17/18.37)
    )


def _ganfeng_params_q1() -> LithiumCompanyParams:
    """赣锋锂业 (002460) Q1预测参数。Q4_2025为基线。

    Q4_2025实际: 赣锋Q4开始扭亏，锂价从底部(~8万)回升至~12万。
    Q4归母净利约5.2亿 (基于Q4锂价~12万、出货~4.5万吨估算)。
    """
    return LithiumCompanyParams(
        name="赣锋锂业",
        code="002460",
        # Q4_2025 基线
        q1_net_profit=5.2,  # Q4归母净利 ~5.2亿
        q1_revenue=95.0,    # Q4营收 ~95亿
        q1_shipment_kt=4.5, # Q4出货 ~4.5万吨
        q1_battery_gwh=7.0, # Q4电池出货 ~7GWh
        # Q1 预估
        q2_shipment_kt=5.0,  # Q1出货 ~5万吨 (公司指引)
        q2_battery_gwh=10.0, # Q1电池 ~10GWh
        # 全年指引
        full_year_shipment_kt=23.0,
        full_year_battery_gwh=43.0,
        # 成本 (Q1实际校准)
        self_supply_ratio=0.68,  # Q1自供率略低于H2
        processing_fee_per_ton=25000,
        minority_interest_ratio=0.15,
        effective_tax_rate=0.15,
        battery_profit_per_wh=0.022,  # Q1电池利润率略低
        other_cost_per_ton=35000,
        non_recurring_ratio=0.23,  # Q1非经常性占比高
    )


# ── 因果传导链 DTO ──────────────────────────────────────────────────────


@dataclass
class CausalChainNode:
    """传导链上一个节点 — 从先行指标到最终业绩的因果链路。

    借鉴 MiroFish PanoramaSearch 的信息传播拓扑追踪思路，
    展示"输入变动1% → 输出变动X%"的杠杆效应。
    """

    step_name: str  # 节点名称 (如"碳酸锂现货价")
    value: float  # 当前值
    unit: str  # 单位 (如"元/吨", "亿")
    formula: str  # 计算逻辑简述
    elasticity_to_price: float  # 碳酸锂现货价±1%时本节点±?%
    weight_to_final: float  # 本节点对最终Q2净利的贡献权重 (0-1)
    is_root: bool = False  # 是否为先行指标根节点
    is_leaf: bool = False  # 是否为最终结果叶节点


# ── 结果 DTO ────────────────────────────────────────────────────────────


@dataclass
class EarningsPreviewResult:
    """Q2 业绩测算结果。"""

    code: str = ""
    name: str = ""
    generated_at: datetime = field(default_factory=datetime.now)

    # 关键输入
    basket: Optional[LithiumBasket] = None

    # 测算结果 (亿元)
    q1_net_profit: float = 0.0
    q2_lithium_gross_profit: float = 0.0  # Q2 锂盐毛利
    q2_battery_profit: float = 0.0  # Q2 电池利润
    q2_net_profit_estimate: float = 0.0  # Q2 归母净利 (基准情形)
    qoq_change_pct: float = 0.0  # Q2 vs Q1 环比变化

    # 敏感性分析
    bull_case: float = 0.0  # 乐观情形 (锂价+10%)
    base_case: float = 0.0  # 基准情形
    bear_case: float = 0.0  # 悲观情形 (锂价-10%)

    # 一致预期对比
    consensus_q2_profit: Optional[float] = None  # 机构一致预期Q2净利
    beat_miss_pct: Optional[float] = None  # vs 一致预期 (正=beat)

    # 数据质量
    confidence: float = 0.80
    data_warnings: list[str] = field(default_factory=list)
    source_summary: str = ""

    # 因果传导链 (借鉴 MiroFish PanoramaSearch)
    causal_chain: list[CausalChainNode] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """一句话总结。"""
        direction = "增长" if self.qoq_change_pct > 0 else "下降"
        beat = ""
        if self.beat_miss_pct is not None:
            beat = (
                f"，较一致预期{'高' if self.beat_miss_pct > 0 else '低'}"
                f"{abs(self.beat_miss_pct):.0f}%"
            )
        return (
            f"{self.name} Q2 归母净利预估 {self.q2_net_profit_estimate:.1f}亿 "
            f"(环比{direction}{abs(self.qoq_change_pct):.0f}%{beat})"
        )


# ── 业绩测算模型 ────────────────────────────────────────────────────────


class EarningsPreviewModel:
    """基于先行指标的业绩测算模型。

    用法:
        model = EarningsPreviewModel.for_ganfeng()
        result = model.preview_q2(basket)
        print(result.summary)
    """

    def __init__(self, params: LithiumCompanyParams):
        self._p = params

    @classmethod
    def for_ganfeng(cls, target_quarter: str = "Q2") -> "EarningsPreviewModel":
        """创建赣锋锂业预设模型。

        Args:
            target_quarter: "Q1" 或 "Q2"
        """
        if target_quarter == "Q1":
            return cls(_ganfeng_params_q1())
        return cls(_ganfeng_params_q2())

    @classmethod
    def custom(cls, **kwargs) -> "EarningsPreviewModel":
        """创建自定义参数模型。可覆盖赣锋默认参数。"""
        p = _ganfeng_params_q2()
        for k, v in kwargs.items():
            if hasattr(p, k):
                setattr(p, k, v)
        return cls(p)

    # ── 核心测算 ────────────────────────────────────────────────────

    def preview_q2(
        self,
        basket: LithiumBasket,
        consensus_q2_profit: Optional[float] = None,
    ) -> EarningsPreviewResult:
        """基于锂盐价格测算Q2业绩。

        Args:
            basket: 锂盐一篮子价格 (Q1+Q2均价)
            consensus_q2_profit: 机构一致预期Q2净利 (亿元), 可选
        """
        warnings: list[str] = []

        # 检查数据质量
        if basket.data_points_q2 < 10:
            warnings.append(
                f"[DATA_GAP] Q2有效数据点仅{basket.data_points_q2}个，"
                "使用参考均价，测算精度下降"
            )
        if basket.source and "reference" in basket.source:
            warnings.append(
                "[DATA_GAP] 价格数据来自参考值而非实时API，"
                "与实际价格可能有±5%偏差"
            )

        # 计算 Q2 加权均价
        q2_price = basket.q2_basket_price
        if q2_price is None:
            q2_price = 165000  # fallback
            warnings.append("[DATA_GAP] Q2加权均价缺失，使用默认值16.5万/吨")

        # 计算 Q1 加权均价
        q1_price = basket.q1_basket_price
        if q1_price is None:
            q1_price = 140000
            warnings.append("[DATA_GAP] Q1加权均价缺失，使用默认值14.0万/吨")

        # ── Q2 锂盐毛利 ──
        # 出货量 (吨)
        q2_tons = self._p.q2_shipment_kt * self._p.wan_ton_to_ton  # 5.5万吨→55000吨

        # 实际售价 = 现货均价 × 折算系数 (长协M-1滞后 + 产品结构折扣)
        realized_price = q2_price * self._p.realization_factor
        realized_q1_price = q1_price * self._p.realization_factor

        # 锂精矿成本 (折人民币/吨碳酸锂)
        spodumene_cost = basket.spodumene_cost_cny
        if spodumene_cost is None:
            spodumene_cost = 1050 * 7.25 * 8  # ~60900
            warnings.append("[DATA_GAP] 锂精矿成本缺失，使用估算值")

        # 综合矿成本: 自供部分成本低(~3.5万/吨)，外购部分按CFR价
        self_mine_cost = 35000  # 自有矿综合成本 ~3.5万/吨
        purchased_cost = spodumene_cost + self._p.processing_fee_per_ton
        blended_ore_cost = (
            self._p.self_supply_ratio * self_mine_cost
            + (1 - self._p.self_supply_ratio) * purchased_cost
        )

        # 全成本 = 矿成本 + 其他成本(SG&A/R&D/运输/折旧)
        all_in_cost = blended_ore_cost + self._p.other_cost_per_ton

        # 单位毛利
        unit_gross_margin = realized_price - all_in_cost

        # Q2 锂盐毛利 (亿元)
        q2_lithium_gross_profit = (
            unit_gross_margin * q2_tons / 1e8
        )

        # ── Q2 电池利润 ──
        q2_battery_profit = (
            self._p.q2_battery_gwh * self._p.battery_profit_per_wh * 10
        )  # GWh × 元/Wh × 10(GWh→Wh/亿) = 亿元

        # ── Q2 归母净利 ──
        q2_pretax = q2_lithium_gross_profit + q2_battery_profit
        q2_net = q2_pretax * (
            1 - self._p.minority_interest_ratio
        ) * (1 - self._p.effective_tax_rate)

        # 加回非经常性损益 (公允价值变动/政府补贴等)
        # Q1实际: 归母18.37亿 vs 扣非14.19亿, 非经常性占比约23%
        nr_ratio = self._p.non_recurring_ratio
        q2_net = q2_net * (1 + nr_ratio)

        # ── QoQ 变化 ──
        qoq = (
            ((q2_net - self._p.q1_net_profit) / self._p.q1_net_profit * 100)
            if self._p.q1_net_profit > 0
            else 0.0
        )

        # ── 敏感性分析 ──
        # 假设锂价 ±10%，出货量 ±10%，均使用折算后实际售价
        bull_price = q2_price * 1.10 * self._p.realization_factor
        bear_price = q2_price * 0.90 * self._p.realization_factor

        bull_margin = bull_price - all_in_cost
        bear_margin = bear_price - all_in_cost

        bull_case = (
            bull_margin * q2_tons / 1e8 * 1.05  # 乐观: 价格↑+出货略增
            + q2_battery_profit * 1.05
        ) * (1 - self._p.minority_interest_ratio) * (
            1 - self._p.effective_tax_rate
        ) * (1 + nr_ratio)

        bear_case = (
            bear_margin * q2_tons / 1e8 * 0.95  # 悲观: 价格↓+出货略减
            + q2_battery_profit * 0.95
        ) * (1 - self._p.minority_interest_ratio) * (
            1 - self._p.effective_tax_rate
        ) * (1 + nr_ratio)

        # ── 一致预期对比 ──
        beat_miss = None
        if consensus_q2_profit and consensus_q2_profit > 0:
            beat_miss = (
                (q2_net - consensus_q2_profit) / consensus_q2_profit * 100
            )

        # ── 因果传导链 ──
        chain = self._compute_causal_chain(
            q2_price=q2_price,
            realized_price=realized_price,
            all_in_cost=all_in_cost,
            unit_margin=unit_gross_margin,
            q2_tons=q2_tons,
            lithium_gross=q2_lithium_gross_profit,
            battery_profit=q2_battery_profit,
            q2_net=q2_net,
            nr_ratio=nr_ratio,
        )

        return EarningsPreviewResult(
            code=self._p.code,
            name=self._p.name,
            basket=basket,
            q1_net_profit=self._p.q1_net_profit,
            q2_lithium_gross_profit=round(q2_lithium_gross_profit, 1),
            q2_battery_profit=round(q2_battery_profit, 1),
            q2_net_profit_estimate=round(q2_net, 1),
            qoq_change_pct=round(qoq, 1),
            bull_case=round(bull_case, 1),
            base_case=round(q2_net, 1),
            bear_case=round(bear_case, 1),
            consensus_q2_profit=consensus_q2_profit,
            beat_miss_pct=round(beat_miss, 1) if beat_miss is not None else None,
            confidence=basket.confidence,
            data_warnings=warnings,
            source_summary=basket.source,
            causal_chain=chain,
        )

    def _compute_causal_chain(
        self,
        q2_price: float,
        realized_price: float,
        all_in_cost: float,
        unit_margin: float,
        q2_tons: float,
        lithium_gross: float,
        battery_profit: float,
        q2_net: float,
        nr_ratio: float,
    ) -> list[CausalChainNode]:
        """计算从碳酸锂现货价到Q2归母净利的因果传导链。

        每个节点标注对上游（碳酸锂现货价）的弹性系数：
          弹性 = (∂本节点/本节点) / (∂碳酸锂价/碳酸锂价)
               = 碳酸锂价变动1%时，本节点变动?%

        经营杠杆效应：固定成本（全成本、税费）不随价格变动，
        使得下游节点的弹性逐级放大。
        """
        # 安全除零
        eps = 1e-8
        safe_price = q2_price if q2_price > 0 else eps
        safe_margin = unit_margin if abs(unit_margin) > eps else eps
        safe_lithium = lithium_gross if abs(lithium_gross) > eps else eps
        safe_net = q2_net if abs(q2_net) > eps else eps

        # 弹性计算:
        # Node 1→2: realized_price = q2_price × rf
        #   elasticity = 1.0 (线性，但受realization_factor约束)
        elasticity_realized = self._p.realization_factor

        # Node 2→3: unit_margin = realized_price − all_in_cost
        #   Δmargin = Δrealized_price
        #   elasticity = (Δmargin/margin) / (Δprice/price)
        #              = (Δprice/margin) / (Δprice/price)
        #              = price / margin
        #   经营杠杆：成本固定，价格变动全部传导到毛利
        elasticity_margin = safe_price / safe_margin

        # Node 3→4: lithium_gross = unit_margin × q2_tons / 1e8
        #   elasticity 与 margin 相同 (线性)
        elasticity_lithium = elasticity_margin

        # Node 4→5: net = (lithium_gross × (1−mi) + battery) × (1−tax) × (1+oi)
        #   电池利润相对固定，锂盐毛利变动时总利润变动:
        #   Δnet = Δlithium_gross × (1−mi) × (1−tax) × (1+oi)
        #   elasticity = (Δnet/net) / (Δlithium/lithium)
        #              = (Δlithium × factor / net) / (Δlithium / lithium)
        #              = (lithium × factor) / net
        factor = (
            (1 - self._p.minority_interest_ratio)
            * (1 - self._p.effective_tax_rate)
            * (1 + nr_ratio)
        )
        net_from_lithium = lithium_gross * factor
        elasticity_net = (
            net_from_lithium / safe_net if safe_net > 0 else 0.0
        )

        # 权重: 碳酸锂现货价变动对Q2净利的综合弹性
        total_elasticity = (
            elasticity_realized
            * (elasticity_margin / elasticity_realized)  # = price/margin
            * (elasticity_net / elasticity_lithium)       # 经营杠杆 + 税费截留
        )
        # 简化: total_elasticity = (price/margin) × (net_from_lithium/net)
        total_elasticity_simple = (
            (safe_price / safe_margin)
            * (net_from_lithium / safe_net)
            if safe_net > 0 and safe_margin > 0
            else 0.0
        )

        chain = [
            CausalChainNode(
                step_name="① 碳酸锂现货价",
                value=q2_price,
                unit="元/吨",
                formula=f"Q2电池级碳酸锂均价",
                elasticity_to_price=1.0,
                weight_to_final=1.0,
                is_root=True,
            ),
            CausalChainNode(
                step_name="② 实际售价 (长协折算)",
                value=realized_price,
                unit="元/吨",
                formula=f"现货价 × {self._p.realization_factor} (长协M-1+产品结构折扣)",
                elasticity_to_price=round(elasticity_realized, 2),
                weight_to_final=round(elasticity_realized, 2),
            ),
            CausalChainNode(
                step_name="③ 单位毛利",
                value=unit_margin,
                unit="元/吨",
                formula=f"实际售价 − 全成本({all_in_cost:,.0f})",
                elasticity_to_price=round(elasticity_margin, 2),
                weight_to_final=round(elasticity_margin / total_elasticity_simple, 2)
                if total_elasticity_simple > 0
                else 0.0,
            ),
            CausalChainNode(
                step_name="④ 锂盐毛利",
                value=lithium_gross,
                unit="亿",
                formula=f"单位毛利 × {q2_tons/10000:.1f}万吨 / 1e8",
                elasticity_to_price=round(elasticity_lithium, 2),
                weight_to_final=round(elasticity_lithium / total_elasticity_simple, 2)
                if total_elasticity_simple > 0
                else 0.0,
            ),
            CausalChainNode(
                step_name="⑤ Q2归母净利",
                value=q2_net,
                unit="亿",
                formula=(
                    f"(锂盐毛利 × {1-self._p.minority_interest_ratio:.0%}"
                    f" + 电池{self._p.q2_battery_gwh}GWh×{self._p.battery_profit_per_wh}元/Wh)"
                    f" × {1-self._p.effective_tax_rate:.0%} × {1+nr_ratio:.0%}"
                ),
                elasticity_to_price=round(total_elasticity_simple, 2),
                weight_to_final=1.0,
                is_leaf=True,
            ),
        ]
        return chain

    def sensitivity_table(
        self, basket: LithiumBasket
    ) -> list[dict]:
        """生成敏感性分析表 — 不同锂价和出货量假设下的Q2利润矩阵。

        返回 5×5 矩阵 (list of row dicts)。
        """
        q2_price = basket.q2_basket_price or 165000
        q2_tons = self._p.q2_shipment_kt * self._p.wan_ton_to_ton

        spodumene_cost = basket.spodumene_cost_cny or 60900
        self_mine_cost = 35000
        purchased_cost = spodumene_cost + self._p.processing_fee_per_ton
        blended_ore_cost = (
            self._p.self_supply_ratio * self_mine_cost
            + (1 - self._p.self_supply_ratio) * purchased_cost
        )
        all_in_cost = blended_ore_cost + self._p.other_cost_per_ton

        price_variations = [0.85, 0.93, 1.00, 1.07, 1.15]  # -15% to +15%
        volume_variations = [0.85, 0.93, 1.00, 1.07, 1.15]

        rows = []
        for v_ratio in volume_variations:
            row = {"volume_ratio": f"{v_ratio:.0%}"}
            ship_tons = q2_tons * v_ratio
            for p_ratio in price_variations:
                realized = q2_price * p_ratio * self._p.realization_factor
                margin = realized - all_in_cost
                lithium_profit = margin * ship_tons / 1e8
                battery_profit = (
                    self._p.q2_battery_gwh
                    * self._p.battery_profit_per_wh
                    * 10
                    * v_ratio
                )
                net = (
                    (lithium_profit + battery_profit)
                    * (1 - self._p.minority_interest_ratio)
                    * (1 - self._p.effective_tax_rate)
                    * (1 + self._p.non_recurring_ratio)
                )
                row[f"price_{p_ratio:.0%}"] = round(net, 1)
            rows.append(row)
        return rows
