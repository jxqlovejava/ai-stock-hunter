# -*- coding: utf-8 -*-
"""绝对估值模型 — 三情景 DCF + 安全边际。

使用模式:
    valuator = DCFValuator()
    result = valuator.valuate("600519", "贵州茅台", free_cashflow=60e8, current_price=1700)
    print(f"公允价值: {result.fair_value:.2f}, 安全边际: {result.margin_of_safety:.1%}")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.fundamental.schema import DCFValuation

logger = logging.getLogger(__name__)


class DCFValuator:
    """DCF 估值器。

    三情景:
      - base: 基准假设
      - bear: 悲观假设（增长率 -30%, WACC +2pp）
      - bull: 乐观假设（增长率 +30%, WACC -1pp）

    输出每股公允价值 + 安全边际。
    """

    def __init__(
        self,
        default_wacc: float = 0.10,
        default_terminal_growth: float = 0.03,
        default_years: int = 10,
    ):
        self._wacc = default_wacc
        self._terminal_g = default_terminal_growth
        self._years = default_years

    def valuate(
        self,
        symbol: str,
        name: str = "",
        free_cashflow: float = 0,
        current_price: float = 0,
        growth_rate: float = 0.08,
        shares_outstanding: Optional[float] = None,
        net_debt: float = 0,
    ) -> DCFValuation:
        """运行 DCF 估值。

        Args:
            symbol: 股票代码
            name: 公司名称
            free_cashflow: 当前自由现金流（元）
            current_price: 当前股价
            growth_rate: 预期 FCF 增长率（base case）
            shares_outstanding: 总股本；None 则假设 1（返回总市值）
            net_debt: 净债务

        Returns:
            DCFValuation
        """
        if free_cashflow <= 0:
            return DCFValuation(
                symbol=symbol, name=name,
                current_price=current_price,
                key_sensitivities=["[DATA_GAP] FCF 数据不可用"],
                data_gaps=["自由现金流数据缺失"],
            )

        shares = shares_outstanding or 1.0

        # 三情景
        base = self._dcf(free_cashflow, growth_rate, self._wacc,
                         self._terminal_g, self._years)
        bear = self._dcf(free_cashflow, growth_rate * 0.5, self._wacc + 0.02,
                         self._terminal_g * 0.5, self._years)
        bull = self._dcf(free_cashflow, growth_rate * 1.5, max(self._wacc - 0.01, 0.06),
                         self._terminal_g * 1.5, self._years)

        # 权益价值
        base_equity = base - net_debt
        fair_value_per_share = base_equity / shares if shares > 0 else 0

        upside = (fair_value_per_share / current_price - 1) if current_price > 0 else 0
        margin_of_safety = (fair_value_per_share - current_price) / fair_value_per_share \
            if fair_value_per_share > 0 else 0

        return DCFValuation(
            symbol=symbol, name=name,
            fair_value=fair_value_per_share,
            current_price=current_price,
            upside_pct=upside,
            margin_of_safety=margin_of_safety,
            bear_case=(bear - net_debt) / shares if shares > 0 else 0,
            base_case=fair_value_per_share,
            bull_case=(bull - net_debt) / shares if shares > 0 else 0,
            wacc=self._wacc,
            terminal_growth=self._terminal_g,
            projection_years=self._years,
            key_sensitivities=[
                f"WACC ±1%: ±{self._sensitivity(free_cashflow, growth_rate, shares, net_debt, self._wacc):.0f}%",
                f"增长率 ±1%: ±{self._sensitivity(free_cashflow, growth_rate + 0.01, shares, net_debt, self._wacc):.0f}%",
            ],
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _dcf(
        fcf: float,
        growth: float,
        wacc: float,
        terminal_g: float,
        years: int,
    ) -> float:
        """折现现金流计算。"""
        total = 0.0
        cf = fcf
        for t in range(1, years + 1):
            cf = cf * (1 + growth)
            pv = cf / ((1 + wacc) ** t)
            total += pv

        # 终值
        terminal_cf = cf * (1 + terminal_g)
        terminal_value = terminal_cf / (wacc - terminal_g)
        total += terminal_value / ((1 + wacc) ** years)
        return total

    def _sensitivity(
        self,
        fcf: float,
        growth: float,
        shares: float,
        net_debt: float,
        wacc: float,
    ) -> float:
        """WACC 敏感性。"""
        base = self._dcf(fcf, growth, wacc, self._terminal_g, self._years)
        perturbed = self._dcf(fcf, growth, wacc + 0.01, self._terminal_g, self._years)
        if base > 0:
            return ((perturbed - net_debt) / shares) / ((base - net_debt) / shares) - 1
        return 0.0
