# -*- coding: utf-8 -*-
"""三情景估值模块。

基于当前价格与基本面指标，给出 bull / base / bear 目标价及隐含涨跌空间。
规则化计算，无 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.utils.decimal_utils import D, safe_divide


@dataclass
class ScenarioValuation:
    """三情景估值结果。"""

    symbol: str
    name: str
    current_price: float
    bull_target: float
    base_target: float
    bear_target: float
    implied_upside: float  # vs current_price
    implied_downside: float  # vs current_price (negative)

    @classmethod
    def from_fundamentals(
        cls,
        symbol: str,
        name: str,
        current_price: float,
        pe_ttm: Optional[float] = None,
        pb: Optional[float] = None,
        roe: Optional[float] = None,
        earnings_growth: Optional[float] = None,
    ) -> "ScenarioValuation":
        """基于 PE/PB/ROE/盈利增速生成三情景目标价。

        规则:
          - base: 当前 PE 按盈利增速调整后的合理估值
          - bull: base * 1.20 (乐观情景)
          - bear: base * 0.75 (悲观情景)
          - 若 PE 无效，使用 PB-ROE 粗略估算
        """
        price = D(current_price)
        pe = D(pe_ttm) if pe_ttm else D("0")
        growth = D(earnings_growth) if earnings_growth else D("0")
        base = price

        if pe > D("0") and growth > D("0"):
            # PEG 启发: 合理 PE ≈ 盈利增速 (%)，当前 PE 相对合理 PE 的折溢价
            fair_pe = growth  # e.g. growth 20% -> fair PE 20
            eps = safe_divide(price, pe)
            base = eps * min(fair_pe, growth * D("1.5"))  # cap at 1.5x growth
        elif pb is not None and roe is not None:
            pb_d = D(pb)
            roe_d = D(roe)
            if pb_d > D("0") and roe_d > D("0"):
                # 合理 PB ≈ ROE(%) / 10
                fair_pb = roe_d / D("10")
                base = price * safe_divide(fair_pb, pb_d)

        bull = base * D("1.20")
        bear = base * D("0.75")

        upside = float(safe_divide(bull - price, price) * D("100"))
        downside = float(safe_divide(bear - price, price) * D("100"))

        return cls(
            symbol=symbol,
            name=name,
            current_price=float(price),
            bull_target=float(bull),
            base_target=float(base),
            bear_target=float(bear),
            implied_upside=upside,
            implied_downside=downside,
        )
