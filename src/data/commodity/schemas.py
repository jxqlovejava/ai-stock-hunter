# -*- coding: utf-8 -*-
"""商品价格 DTO — 通用商品价格 + 锂盐一篮子价格模型。

设计原则:
  - 全部使用 Pydantic BaseModel，字段 Optional
  - source 字段追踪数据来源
  - 价格数据新鲜度: 日度商品报价有效期 24h
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.data.source_citation import SourceCitation


# ---------------------------------------------------------------------------
# 商品类型枚举
# ---------------------------------------------------------------------------


class CommodityType(str, Enum):
    """大宗商品类型 — 当前仅覆盖锂电产业链，后续可扩展到铜/原油/黄金等。"""

    BATTERY_LI2CO3 = "battery_lithium_carbonate"  # 电池级碳酸锂
    INDUSTRIAL_LI2CO3 = "industrial_lithium_carbonate"  # 工业级碳酸锂
    BATTERY_LIOH = "battery_lithium_hydroxide"  # 电池级氢氧化锂
    SPODUMENE_6 = "spodumene_6pct"  # 锂辉石精矿 (6% Li₂O, CFR中国)
    LEPIDOLITE = "lepidolite"  # 锂云母精矿
    COPPE = "copper"  # 铜 (预留)
    CRUDE_OIL = "crude_oil"  # 原油 (预留)

    @property
    def label(self) -> str:
        _labels = {
            self.BATTERY_LI2CO3: "电池级碳酸锂",
            self.INDUSTRIAL_LI2CO3: "工业级碳酸锂",
            self.BATTERY_LIOH: "电池级氢氧化锂",
            self.SPODUMENE_6: "锂辉石精矿(6% Li₂O)",
            self.LEPIDOLITE: "锂云母精矿",
            self.COPPE: "铜",
            self.CRUDE_OIL: "原油",
        }
        return _labels.get(self, self.value)

    @property
    def price_unit(self) -> str:
        """价格单位。"""
        _units = {
            self.BATTERY_LI2CO3: "元/吨",
            self.INDUSTRIAL_LI2CO3: "元/吨",
            self.BATTERY_LIOH: "元/吨",
            self.SPODUMENE_6: "USD/吨",
            self.LEPIDOLITE: "元/吨",
            self.COPPE: "USD/吨",
            self.CRUDE_OIL: "USD/桶",
        }
        return _units.get(self, "")


# ---------------------------------------------------------------------------
# 商品价格 DTO
# ---------------------------------------------------------------------------


class CommodityPrice(BaseModel):
    """单日商品价格数据点。

    所有字段 Optional，缺失数据标注 None。
    """

    commodity: CommodityType = Field(description="商品类型")
    date: datetime = Field(description="价格日期")
    price: Optional[float] = Field(default=None, description="收盘/现货价格")
    open: Optional[float] = Field(default=None, description="开盘价（期货）")
    high: Optional[float] = Field(default=None, description="最高价")
    low: Optional[float] = Field(default=None, description="最低价")
    change_pct: Optional[float] = Field(default=None, description="较前日涨跌幅(%)")
    avg_price_period: Optional[float] = Field(
        default=None, description="期间均价（如Q2均价）"
    )
    source: str = Field(default="", description="数据源标识")
    citation: Optional[SourceCitation] = Field(
        default=None, description="数据溯源信息"
    )


# ---------------------------------------------------------------------------
# 锂盐日度价格点
# ---------------------------------------------------------------------------


class LithiumPricePoint(BaseModel):
    """锂盐单日价格快照 — 含碳酸锂+氢氧化锂+锂精矿。"""

    date: datetime = Field(description="交易日")
    carbonate_battery: Optional[float] = Field(
        default=None, description="电池级碳酸锂均价 (元/吨)"
    )
    carbonate_industrial: Optional[float] = Field(
        default=None, description="工业级碳酸锂均价 (元/吨)"
    )
    hydroxide_battery: Optional[float] = Field(
        default=None, description="电池级氢氧化锂均价 (元/吨)"
    )
    spodumene_cfr: Optional[float] = Field(
        default=None, description="锂辉石精矿CFR中国 (USD/吨)"
    )
    source: str = Field(default="", description="数据源")


# ---------------------------------------------------------------------------
# 锂盐价格序列
# ---------------------------------------------------------------------------


class LithiumPriceSeries(BaseModel):
    """某时间段锂盐价格序列，含统计摘要。"""

    commodity: CommodityType = Field(description="商品类型")
    start_date: datetime = Field(description="起始日期")
    end_date: datetime = Field(description="结束日期")
    daily: list[LithiumPricePoint] = Field(
        default_factory=list, description="日度价格点"
    )
    avg_price: Optional[float] = Field(default=None, description="期间均价")
    max_price: Optional[float] = Field(default=None, description="期间最高价")
    min_price: Optional[float] = Field(default=None, description="期间最低价")
    data_points: int = Field(default=0, description="有效数据点数")
    source: str = Field(default="", description="主数据源")


# ---------------------------------------------------------------------------
# 锂盐一篮子价格（用于业绩测算）
# ---------------------------------------------------------------------------


class LithiumBasket(BaseModel):
    """锂盐一篮子价格 + 成本价差 — 业绩测算的核心输入。

    Q2 利润公式：
      Q2锂盐毛利 ≈ Q2出货量 × (basket_price − spodumene_cost − processing_fee)
      其中 basket_price = carbonate_battery_weight × carbonate_price
                          + hydroxide_weight × hydroxide_price
    """

    # --- 产品价格 (元/吨) ---
    carbonate_q1_avg: Optional[float] = Field(
        default=None, description="Q1 电池级碳酸锂均价"
    )
    carbonate_q2_avg: Optional[float] = Field(
        default=None, description="Q2 电池级碳酸锂均价"
    )
    hydroxide_q1_avg: Optional[float] = Field(
        default=None, description="Q1 电池级氢氧化锂均价"
    )
    hydroxide_q2_avg: Optional[float] = Field(
        default=None, description="Q2 电池级氢氧化锂均价"
    )

    # --- 成本端 ---
    spodumene_q1_avg: Optional[float] = Field(
        default=None, description="Q1 锂辉石精矿CFR均价 (USD/吨)"
    )
    spodumene_q2_avg: Optional[float] = Field(
        default=None, description="Q2 锂辉石精矿CFR均价 (USD/吨)"
    )
    processing_fee: float = Field(
        default=25000, description="加工费估算 (元/吨), 默认25000"
    )

    # --- 汇率 ---
    usd_cny_rate: float = Field(default=7.25, description="USD/CNY 汇率")

    # --- 权重 (赣锋产品结构) ---
    carbonate_weight: float = Field(
        default=0.65, description="碳酸锂占锂盐收入权重"
    )
    hydroxide_weight: float = Field(
        default=0.35, description="氢氧化锂占锂盐收入权重"
    )

    # --- 数据质量 ---
    source: str = Field(default="", description="主数据源")
    data_points_q2: int = Field(default=0, description="Q2有效数据点数")
    confidence: float = Field(
        default=0.80, ge=0.0, le=1.0, description="数据置信度"
    )

    @property
    def q2_basket_price(self) -> Optional[float]:
        """Q2 加权平均售价 (元/吨)。"""
        if self.carbonate_q2_avg is None and self.hydroxide_q2_avg is None:
            return None
        c = self.carbonate_q2_avg or 0
        h = self.hydroxide_q2_avg or 0
        w = self.carbonate_weight + self.hydroxide_weight
        return (c * self.carbonate_weight + h * self.hydroxide_weight) / w if w > 0 else None

    @property
    def q1_basket_price(self) -> Optional[float]:
        """Q1 加权平均售价 (元/吨)。"""
        if self.carbonate_q1_avg is None and self.hydroxide_q1_avg is None:
            return None
        c = self.carbonate_q1_avg or 0
        h = self.hydroxide_q1_avg or 0
        w = self.carbonate_weight + self.hydroxide_weight
        return (c * self.carbonate_weight + h * self.hydroxide_weight) / w if w > 0 else None

    @property
    def qoq_price_change_pct(self) -> Optional[float]:
        """Q2 vs Q1 均价变化(%)。"""
        q1 = self.q1_basket_price
        q2 = self.q2_basket_price
        if q1 and q2 and q1 > 0:
            return round((q2 - q1) / q1 * 100, 1)
        return None

    @property
    def spodumene_cost_cny(self) -> Optional[float]:
        """锂精矿成本折人民币 (元/吨碳酸锂)。约8吨精矿产1吨碳酸锂。"""
        if self.spodumene_q2_avg is None:
            return None
        return self.spodumene_q2_avg * self.usd_cny_rate * 8

    @property
    def estimated_unit_gross_margin(self) -> Optional[float]:
        """估算单位毛利 (元/吨碳酸锂当量)。"""
        basket = self.q2_basket_price
        cost = self.spodumene_cost_cny
        if basket is None:
            return None
        ore_cost = cost or 60000  # 默认外购矿成本约6万/吨
        return basket - ore_cost - self.processing_fee
